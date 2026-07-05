# market_brief/data/price_data.py — market_brief_v1.0.0
"""
Price lookups for [premium]/[platinum] SIGNAL VALIDATION only.

Yahoo Finance has no official public API — it was shut down in 2017. This
module hits Yahoo's UNOFFICIAL chart endpoint (the same one the yfinance
library wraps under the hood). That means: no SLA, no documented rate limit,
it can be throttled, CAPTCHA'd, or change shape without notice, and data is
delayed ~15-20 minutes during market hours.

Deliberately scoped narrow to manage that risk: this is used ONLY as an
internal backend signal for the `validation` table (comparing composite
scores to what price actually did afterward) — it is never surfaced to a
customer as a quote, chart, or price feature. That keeps the ToS/legal
exposure to "we check our own homework internally," not "we resell Yahoo's
data," which matters given real subscribers are the goal here.

Ticker mapping: Yahoo does not recognize the bare index ticker "SPX" — it
needs "^GSPC". Mapped explicitly below so this can't repeat the same
^GSPC-vs-SPX mismatch that has previously bitten options_trader's ORB fetch.

This module could not be exercised against the live endpoint from the build
sandbox (query1.finance.yahoo.com isn't reachable there) — verify with
`python main.py --testfeeds` on a box with real internet access before
relying on it.

Last updated: 2026-07-05
"""

from __future__ import annotations

import time

import requests

import config

# Yahoo has no bare "SPX" symbol — extend this map if other universe tickers
# ever need a Yahoo-specific alias.
YAHOO_SYMBOL_MAP = {
    "SPX": "^GSPC",
}

# A bare `requests` default User-Agent is a common, easy block trigger on
# unofficial endpoints; a normal browser UA reduces (does not eliminate) that.
_HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"),
}


def _yahoo_symbol(ticker: str) -> str:
    return YAHOO_SYMBOL_MAP.get(ticker, ticker)


def fetch_price(ticker: str) -> float | None:
    """Best-effort last/regular-market price for `ticker`. None on ANY
    failure (network, block, missing field) — callers must treat that ticker
    as simply unresolved this cycle, not as a fatal error."""
    symbol = _yahoo_symbol(ticker)
    url = config.YAHOO_CHART_URL.format(symbol=symbol)
    try:
        r = requests.get(url, params={"interval": "1d", "range": "1d"},
                         headers=_HEADERS, timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
        result = (data.get("chart") or {}).get("result") or []
        if not result:
            err = (data.get("chart") or {}).get("error")
            print(f"[price_data] {ticker} ({symbol}): no chart result ({err})")
            return None
        meta = result[0].get("meta") or {}
        price = meta.get("regularMarketPrice")
        if price is None:
            print(f"[price_data] {ticker} ({symbol}): no regularMarketPrice in meta")
            return None
        return float(price)
    except Exception as exc:
        print(f"[price_data] {ticker} ({symbol}) fetch error: {exc}")
        return None


def fetch_prices(tickers: list[str], max_tickers: int | None = None,
                 pause_s: float = 0.35) -> dict[str, float]:
    """Sequential best-effort price fetch with a small delay between calls.
    An unofficial endpoint with no documented rate limit is not the place to
    fire concurrent requests — sequential + a short pause is the conservative
    choice, and this only ever runs once/day per validated ticker anyway."""
    max_tickers = max_tickers or config.VALIDATION_MAX_TICKERS
    subset = tickers[:max_tickers]
    out: dict[str, float] = {}
    for i, t in enumerate(subset):
        p = fetch_price(t)
        if p is not None:
            out[t] = p
        if i < len(subset) - 1:
            time.sleep(pause_s)
    print(f"[price_data] resolved {len(out)}/{len(subset)} prices")
    return out
