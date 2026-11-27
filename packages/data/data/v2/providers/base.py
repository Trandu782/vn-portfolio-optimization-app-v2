"""Shared plumbing for the V2 adapters.

This mirrors the request/response classification in the V1 ``ProviderBase`` but
is self-contained so the V2 layer never imports a V1 provider module. That small
overlap is deliberate and recorded in ADR 0003: it keeps V1 untouched and lets
the two layers evolve independently.

HTTP handling follows the V2 contract:
- 403 -> :class:`data.v2.errors.BlockedError` (no retry, cool down)
- 401 -> :class:`data.errors.AuthRequiredError`
- 429 -> :class:`data.errors.RateLimitError` (the runner retries with backoff)
- HTML / anti-bot body -> :class:`data.errors.AuthRequiredError`
- a missing field -> :class:`data.errors.SchemaError` (failover moves on)
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, timedelta
from typing import Any

from core.validation import MAX_CHUNKS
from data.errors import (
    AuthRequiredError,
    HttpStatusError,
    NetworkError,
    ProviderTimeoutError,
    RateLimitError,
    SchemaError,
)
from data.http import HttpClient, HttpRequestError, HttpResponse
from data.v2.config import V2DataSettings, get_v2_settings
from data.v2.errors import BlockedError

#: JSON keys that may carry a bar's date, most-specific first.
DATE_KEYS: tuple[str, ...] = ("tradingDate", "time", "date", "t")
OPEN_KEYS: tuple[str, ...] = ("open", "o")
HIGH_KEYS: tuple[str, ...] = ("high", "h")
LOW_KEYS: tuple[str, ...] = ("low", "l")
CLOSE_KEYS: tuple[str, ...] = ("close", "c")
VOLUME_KEYS: tuple[str, ...] = ("volume", "v")
VALUE_KEYS: tuple[str, ...] = ("value", "tradingValue", "turnover")

#: UDF array letters used to zip parallel arrays into rows.
UDF_LETTERS: dict[str, str] = {
    "t": "time",
    "o": "open",
    "h": "high",
    "l": "low",
    "c": "close",
    "v": "volume",
}


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
    if isinstance(value, bool):
        raise ValueError("boolean is not a date")
    if isinstance(value, (int, float)):
        timestamp = float(value)
        if timestamp > 1e11:  # milliseconds since the epoch
            timestamp /= 1000.0
        return datetime.fromtimestamp(timestamp, tz=UTC).date()
    text = str(value).strip()
    if text.isdigit() and len(text) >= 9:  # unix seconds/ms sent as a string (VCI 't')
        return coerce_date(int(text))
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


def zip_udf_rows(payload: Any, *, provider: str) -> list[dict[str, Any]]:
    """Turn a TradingView UDF document (or list of them) into row dicts."""
    document = payload
    if isinstance(payload, Mapping) and "data" in payload:
        document = payload["data"]
    if isinstance(document, Mapping) and isinstance(document.get("t"), list):
        return _zip_document(document, provider=provider)
    if isinstance(document, list) and document:
        first = document[0]
        if isinstance(first, Mapping) and isinstance(first.get("t"), list):
            return _zip_document(first, provider=provider)
    return []


def _zip_document(document: Mapping[str, Any], *, provider: str) -> list[dict[str, Any]]:
    times = document["t"]
    columns = {name: document.get(letter, []) for letter, name in UDF_LETTERS.items()}
    for name, values in columns.items():
        if not isinstance(values, list) or len(values) != len(times):
            raise SchemaError(
                f"{provider} UDF column {name!r} is not aligned with 't'", provider=provider
            )
    return [{name: columns[name][index] for name in columns} for index in range(len(times))]


def unwrap_rows(payload: Any) -> list[Any]:
    """Unwrap the common ``{"data": [...]}`` container into a row list."""
    rows: Any = payload
    if isinstance(payload, Mapping):
        inner = payload.get("data", payload.get("Data"))
        if isinstance(inner, list):
            rows = inner
        elif isinstance(inner, Mapping) and isinstance(inner.get("data"), list):
            rows = inner["data"]
    if not isinstance(rows, list):
        raise SchemaError("payload is not a list of rows")
    return rows


class V2ProviderBase:
    """Base class carrying the shared HTTP plumbing for a V2 adapter."""

    id: str = "base"
    display_name: str = "Base V2 provider"
    unofficial: bool = True

    def __init__(self, http: HttpClient, settings: V2DataSettings | None = None) -> None:
        self._http = http
        self._settings = settings or get_v2_settings()

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
        """POST ``url`` with a JSON body and return decoded JSON."""
        try:
            response = self._http.post(url, json=json_body, headers=headers)
        except HttpRequestError as exc:
            if exc.timeout:
                raise ProviderTimeoutError(str(exc), provider=self.id, cause=exc) from exc
            raise NetworkError(str(exc), provider=self.id, cause=exc) from exc
        return self._decode(response)

    def _decode(self, response: HttpResponse) -> Any:
        """Turn a raw response into JSON or a classified error."""
        status = response.status_code
        if status == 403:
            raise BlockedError(f"{self.id} blocked (HTTP 403)", provider=self.id)
        if status == 401:
            raise AuthRequiredError(
                f"{self.id} now requires authentication (HTTP 401)", provider=self.id
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
        if start > end:
            raise ValueError("start must not be after end")
        if days <= 0:
            raise ValueError("days must be positive")
        windows: list[tuple[date, date]] = []
        cursor = start
        while cursor <= end:
            if len(windows) >= MAX_CHUNKS:
                raise ValueError(f"date range exceeds maximum of {MAX_CHUNKS} chunks")
            window_end = min(cursor + timedelta(days=days - 1), end)
            windows.append((cursor, window_end))
            cursor = window_end + timedelta(days=1)
        return windows


__all__ = [
    "CLOSE_KEYS",
    "DATE_KEYS",
    "HIGH_KEYS",
    "LOW_KEYS",
    "OPEN_KEYS",
    "VALUE_KEYS",
    "VOLUME_KEYS",
    "V2ProviderBase",
    "coerce_date",
    "coerce_float",
    "coerce_int",
    "pick",
    "unwrap_rows",
    "zip_udf_rows",
]
