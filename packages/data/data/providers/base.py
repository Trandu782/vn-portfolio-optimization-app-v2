"""Shared machinery for the unofficial providers.

A provider only has to describe *where* a resource lives and *which* JSON keys
carry the numbers; everything else (HTTP error classification, date chunking,
unix-timestamp conversion, schema errors) lives here. Field names are passed in
explicitly by each provider and are never guessed at runtime: a missing key
raises :class:`SchemaError` so the failover chain moves on instead of silently
serving wrong numbers.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from data.errors import (
    AuthRequiredError,
    HttpStatusError,
    NetworkError,
    ProviderTimeoutError,
    RateLimitError,
    SchemaError,
)
from data.http import HttpClient, HttpRequestError, HttpResponse
from data.models import PriceBar
from data.settings import DataSettings, get_settings

#: JSON keys that may carry a bar's date, most-specific first.
DATE_KEYS: tuple[str, ...] = ("tradingDate", "date", "time", "Date", "Time")
OPEN_KEYS: tuple[str, ...] = ("open", "o", "Open")
HIGH_KEYS: tuple[str, ...] = ("high", "h", "High")
LOW_KEYS: tuple[str, ...] = ("low", "l", "Low")
CLOSE_KEYS: tuple[str, ...] = ("close", "c", "Close")
VOLUME_KEYS: tuple[str, ...] = ("volume", "v", "Volume")
VALUE_KEYS: tuple[str, ...] = ("value", "tradingValue", "Value", "turnover")
ADJ_KEYS: tuple[str, ...] = ("adj_close", "adjClose", "adjustedClose")


def pick(row: Mapping[str, Any], keys: Sequence[str], *, required: bool = True) -> Any:
    """Return the first present, non-empty value among ``keys``."""
    for key in keys:
        if key in row and row[key] is not None and row[key] != "":
            return row[key]
    if required:
        raise KeyError(keys[0])
    return None


def coerce_date(value: Any) -> date:
    """Convert an ISO date, datetime string or unix timestamp to a ``date``."""
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, bool):  # bool is an int subclass; reject it
        raise ValueError("boolean is not a date")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1e11:  # milliseconds since the epoch
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=UTC).date()
    text = str(value).strip()
    try:
        return date.fromisoformat(text[:10])
    except ValueError:
        for fmt in ("%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d"):
            try:
                return datetime.strptime(text, fmt).date()
            except ValueError:
                continue
    raise ValueError(f"unrecognised date: {value!r}")


def coerce_float(value: Any) -> float:
    """Convert a number or numeric string to ``float``."""
    if isinstance(value, bool):
        raise ValueError("boolean is not a number")
    return float(value)


def coerce_int(value: Any) -> int:
    """Convert a number or numeric string to ``int`` (rounding floats)."""
    return round(coerce_float(value))


class ProviderBase:
    """Base class carrying the shared plumbing for a provider."""

    id: str = "base"
    display_name: str = "Base provider"
    returns_adjusted_prices: bool = False
    supports_indexes: bool = True
    unofficial: bool = True

    def __init__(self, http: HttpClient, settings: DataSettings | None = None) -> None:
        self._http = http
        self._settings = settings or get_settings()

    # -- HTTP ---------------------------------------------------------------
    def _get_json(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """GET ``url`` and return decoded JSON, classifying every failure."""
        try:
            response = self._http.get(url, params=params, headers=headers)
        except HttpRequestError as exc:
            if exc.timeout:
                raise ProviderTimeoutError(str(exc), provider=self.id, cause=exc) from exc
            raise NetworkError(str(exc), provider=self.id, cause=exc) from exc
        return self._decode(response)

    def _post_json(
        self,
        url: str,
        *,
        json_body: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> Any:
        """POST ``url`` with a JSON body and return decoded JSON, classifying failures."""
        try:
            response = self._http.post(url, json=json_body, headers=headers)
        except HttpRequestError as exc:
            if exc.timeout:
                raise ProviderTimeoutError(str(exc), provider=self.id, cause=exc) from exc
            raise NetworkError(str(exc), provider=self.id, cause=exc) from exc
        return self._decode(response)

    def _decode(self, response: HttpResponse) -> Any:
        """Turn an :class:`HttpResponse` into JSON or a classified error."""
        status = response.status_code
        if status in (401, 403):
            raise AuthRequiredError(
                f"{self.id} now requires authentication (HTTP {status})", provider=self.id
            )
        if status == 429:
            raise RateLimitError(f"{self.id} rate limited (HTTP 429)", provider=self.id)
        if status >= 400:
            raise HttpStatusError(
                f"{self.id} returned HTTP {status}", status_code=status, provider=self.id
            )
        text = response.text.strip()
        if text.startswith("<"):
            raise AuthRequiredError(
                f"{self.id} returned HTML instead of JSON (blocked or auth wall)",
                provider=self.id,
            )
        try:
            payload = response.json()
        except ValueError as exc:
            raise SchemaError(
                f"{self.id} returned invalid JSON", provider=self.id, cause=exc
            ) from exc
        if self._is_auth_payload(payload):
            message = payload.get("message", "") if isinstance(payload, Mapping) else ""
            raise AuthRequiredError(
                f"{self.id} now requires authentication: {message}", provider=self.id
            )
        return payload

    @staticmethod
    def _is_auth_payload(payload: Any) -> bool:
        """Detect token/auth failures that arrive with an HTTP 200 body."""
        if not isinstance(payload, Mapping):
            return False
        code = str(payload.get("code", "")).upper()
        message = str(payload.get("message", "")).lower()
        return (
            "INVALID_TOKEN" in code
            or "UNAUTHORIZED" in code
            or "UNAUTHENTICATED" in code
            or "token is invalid" in message
            or "unauthorized" in message
        )

    # -- dates --------------------------------------------------------------
    @staticmethod
    def _unix(day: date) -> int:
        """Return midnight UTC of ``day`` as a unix timestamp."""
        return int(datetime(day.year, day.month, day.day, tzinfo=UTC).timestamp())

    @staticmethod
    def _chunks(start: date, end: date, days: int = 365) -> list[tuple[date, date]]:
        """Split ``[start, end]`` into inclusive windows of at most ``days`` days."""
        windows: list[tuple[date, date]] = []
        cursor = start
        while cursor <= end:
            window_end = min(cursor + timedelta(days=days - 1), end)
            windows.append((cursor, window_end))
            cursor = window_end + timedelta(days=1)
        return windows

    # -- parsing ------------------------------------------------------------
    def _rows(self, payload: Any) -> list[Any]:
        """Unwrap the common ``{"data": [...]}`` container and validate shape."""
        rows: Any = payload
        if isinstance(payload, Mapping):
            inner = payload.get("data", payload.get("Data"))
            if isinstance(inner, list):
                rows = inner
            elif isinstance(inner, Mapping) and isinstance(inner.get("data"), list):
                rows = inner["data"]
        if not isinstance(rows, list):
            raise SchemaError(
                f"{self.id} payload is not a list of rows", provider=self.id
            )
        return rows

    def _parse_rows(
        self,
        rows: Sequence[Mapping[str, Any]],
        *,
        date_keys: Sequence[str] = DATE_KEYS,
    ) -> list[PriceBar]:
        """Map raw rows to :class:`PriceBar`, raising ``SchemaError`` on gaps."""
        bars: list[PriceBar] = []
        for row in rows:
            if not isinstance(row, Mapping):
                raise SchemaError(f"{self.id} row is not an object", provider=self.id)
            try:
                day = coerce_date(pick(row, date_keys))
                close = coerce_float(pick(row, CLOSE_KEYS))
                open_raw = pick(row, OPEN_KEYS, required=False)
                high_raw = pick(row, HIGH_KEYS, required=False)
                low_raw = pick(row, LOW_KEYS, required=False)
                volume_raw = pick(row, VOLUME_KEYS, required=False)
                value_raw = pick(row, VALUE_KEYS, required=False)
                adj_raw = pick(row, ADJ_KEYS, required=False)
            except (KeyError, ValueError, TypeError) as exc:
                raise SchemaError(
                    f"{self.id} row does not match the documented schema: {exc}",
                    provider=self.id,
                    cause=exc,
                ) from exc
            open_price = coerce_float(open_raw) if open_raw is not None else close
            high = coerce_float(high_raw) if high_raw is not None else close
            low = coerce_float(low_raw) if low_raw is not None else close
            volume = coerce_int(volume_raw) if volume_raw is not None else 0
            value = coerce_float(value_raw) if value_raw is not None else None
            if self.returns_adjusted_prices and adj_raw is not None:
                adj_close = coerce_float(adj_raw)
            else:
                adj_close = close
            bars.append(
                PriceBar(
                    date=day,
                    open=open_price,
                    high=high,
                    low=low,
                    close=close,
                    adj_close=adj_close,
                    volume=volume,
                    value=value,
                    source=self.id,
                )
            )
        return bars
