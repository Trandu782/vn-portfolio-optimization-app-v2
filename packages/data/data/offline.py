"""Recorded-fixture HTTP client for tests and offline runs.

``StaticHttpClient`` returns canned responses keyed by a substring of the request
URL, so providers can be exercised end-to-end without touching the network. This
is the client tests inject and the client the ``--offline`` sync mode uses; the
production path uses ``HttpxHttpClient`` instead.
"""

from __future__ import annotations

import json as _json
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

from data.http import HttpResponse


@dataclass
class StaticHttpClient:
    """Serve recorded bodies keyed by a URL substring (``"/bars-long-term"`` ...)."""

    routes: Mapping[str, Any]
    default_status: int = 404
    calls: list[str] = field(default_factory=list)

    def get(
        self,
        url: str,
        *,
        params: Mapping[str, str | int | float] | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Return the first matching canned response, or a 404."""
        return self._respond(url)

    def post(
        self,
        url: str,
        *,
        json: Any = None,
        headers: Mapping[str, str] | None = None,
    ) -> HttpResponse:
        """Return the first matching canned response for a POST, or a 404."""
        return self._respond(url)

    def _respond(self, url: str) -> HttpResponse:
        """Return the first route whose token appears in ``url``, or a 404."""
        self.calls.append(url)
        for token, value in self.routes.items():
            if token in url:
                if isinstance(value, BaseException):
                    raise value
                if isinstance(value, HttpResponse):
                    return value
                return HttpResponse(200, _json.dumps(value, default=str), url)
        return HttpResponse(self.default_status, "", url)
