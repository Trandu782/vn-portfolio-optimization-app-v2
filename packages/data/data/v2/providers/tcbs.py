"""TCBS V2 ratios adapter (last resort).

Candidate endpoint: ``GET /fundamental-analysis/v1/finance/ratio/{ticker}`` with
``yearly`` and ``isAll``. Field names follow the open-source vnstock TCBS
adapter. Percentages are normalized to 0-100 numbers by the shared parser.

From the sandbox TCBS is behind a Cloudflare challenge (HTTP 403 HTML), so this
adapter is implemented but **excluded** from the active ratios chain until it is
confirmed on the deployed / GitHub runner.
"""

from __future__ import annotations

from typing import ClassVar

from data.v2.providers.base import V2ProviderBase
from data.v2.providers.parsing import parse_financial_ratios
from data.v2.registry import ProviderParams, ratios_providers
from data.v2.schemas import FinancialRatios


class TcbsAdapter(V2ProviderBase):
    """Reads financial ratios from TCBS's public fundamental-analysis endpoint."""

    id = "tcbs"
    display_name = "TCBS (unofficial)"
    returns_adjusted = False

    BASE_URL = "https://apipubaws.tcbs.com.vn"
    RATIOS_PATH = "/fundamental-analysis/v1/finance/ratio/{ticker}"
    HEADERS: ClassVar[dict[str, str]] = {
        "Referer": "https://tcinvest.tcbs.com.vn/",
        "Origin": "https://tcinvest.tcbs.com.vn",
    }

    def get_ratios(self, ticker: str) -> list[FinancialRatios]:
        """Return ratios from TCBS (candidate endpoint; unverified)."""
        code = ticker.upper()
        payload = self._get_json(
            self.BASE_URL + self.RATIOS_PATH.format(ticker=code),
            params={"yearly": 0, "isAll": "true"},
            headers=self.HEADERS,
        )
        return parse_financial_ratios(payload, ticker=code, provider=self.id)


__all__ = ["TcbsAdapter"]


ratios_providers.register(
    id="tcbs",
    name="TCBS ratios (unofficial, unverified)",
    description="TCBS financial ratios via fundamental-analysis (Cloudflare-gated; unverified).",
    parameter_schema=ProviderParams,
)(TcbsAdapter)
