# market_brief/data/sources.py — market_brief_v1.4.0
"""
News ingestion from APIs (never scraping paywalled sites).

Sources, gated by tier via config.TierSpec.sources:
  - finnhub      : /company-news per ticker  (free tier OK)
  - alphavantage : NEWS_SENTIMENT batch call (free tier: 25 req/day -> 1 call)
  - benzinga     : /api/v2/news             (premium; paid key)

Every source normalizes to Article. Missing key => that source is skipped
with a warning; the run continues (free tier still works on Finnhub alone).

AV/Finnhub also return a baseline sentiment we carry as a pre-LLM hint —
this is the "cheap stage" that lets Haiku/Sonnet focus only on what matters.

Last updated: 2026-07-04
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any

import requests

import config

# Indices / pseudo-tickers that equity news endpoints don't cover.
_NON_EQUITY = {"SPX"}

# AV's NEWS_SENTIMENT "tickers" filter has no documented count cap, but every
# example AV itself publishes uses 1-3 tickers, and in practice a full ~28-name
# list reliably triggers a blanket "Invalid inputs" (the whole request fails,
# not a partial match). Rather than gamble on the exact undocumented limit,
# cap to a priority subset; if that call still fails, fall back to an
# unfiltered market-news pull so AV degrades gracefully instead of going dark.
AV_MAX_TICKERS = 10


@dataclass
class Article:
    source: str
    url: str
    title: str
    body: str
    published_utc: dt.datetime
    tickers_hint: list[str] = field(default_factory=list)
    baseline_sentiment: float | None = None   # provider score, -1..1 ish


def _utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def _equity_universe() -> list[str]:
    return [t for t in config.UNIVERSE if t not in _NON_EQUITY]


# --------------------------------------------------------------------------
# Finnhub
# --------------------------------------------------------------------------
def fetch_finnhub(key: str, lookback_hours: int) -> list[Article]:
    if not key:
        print("[sources] FINNHUB_API_KEY missing -> skipping Finnhub")
        return []
    since = _utc_now() - dt.timedelta(hours=lookback_hours)
    frm = since.date().isoformat()
    to = _utc_now().date().isoformat()
    out: list[Article] = []
    for sym in _equity_universe():
        try:
            r = requests.get(
                "https://finnhub.io/api/v1/company-news",
                params={"symbol": sym, "from": frm, "to": to, "token": key},
                timeout=config.HTTP_TIMEOUT,
            )
            r.raise_for_status()
            for item in r.json() or []:
                ts = item.get("datetime")
                if not ts:
                    continue
                pub = dt.datetime.fromtimestamp(ts, tz=dt.timezone.utc)
                if pub < since:
                    continue
                related = [s.strip() for s in str(item.get("related", "")).split(",") if s.strip()]
                out.append(Article(
                    source="finnhub",
                    url=item.get("url", ""),
                    title=item.get("headline", ""),
                    body=item.get("summary", ""),
                    published_utc=pub,
                    tickers_hint=[s for s in (related or [sym]) if s in config.UNIVERSE],
                ))
        except Exception as exc:
            print(f"[sources] finnhub {sym} error: {exc}")
    print(f"[sources] finnhub: {len(out)} articles")
    return out


# --------------------------------------------------------------------------
# Alpha Vantage NEWS_SENTIMENT  (baseline sentiment is the free pre-filter)
# --------------------------------------------------------------------------
def fetch_alphavantage(key: str, lookback_hours: int, limit: int = 200) -> list[Article]:
    if not key:
        print("[sources] ALPHAVANTAGE_API_KEY missing -> skipping Alpha Vantage")
        return []
    since = _utc_now() - dt.timedelta(hours=lookback_hours)
    time_from = since.strftime("%Y%m%dT%H%M")

    # CORE_TRADED first (highest priority), capped — see AV_MAX_TICKERS note.
    priority = config.CORE_TRADED + [t for t in _equity_universe() if t not in config.CORE_TRADED]
    tickers_subset = [t for t in priority if t not in _NON_EQUITY][:AV_MAX_TICKERS]

    result = _av_call(key, {"tickers": ",".join(tickers_subset), "time_from": time_from,
                            "sort": "LATEST", "limit": limit})
    if result is None:
        print(f"[sources] alphavantage tickers filter failed -> retrying unfiltered "
              f"(financial_markets topic, no tickers)")
        result = _av_call(key, {"topics": "financial_markets", "time_from": time_from,
                                "sort": "LATEST", "limit": limit})
    if result is None:
        return []

    out: list[Article] = []
    for item in result:
        try:
            pub = dt.datetime.strptime(item["time_published"], "%Y%m%dT%H%M%S").replace(
                tzinfo=dt.timezone.utc)
        except (KeyError, ValueError):
            continue
        if pub < since:
            continue
        hints, best = [], None
        for ts in item.get("ticker_sentiment", []):
            sym = ts.get("ticker")
            if sym in config.UNIVERSE:
                hints.append(sym)
                try:
                    rel = float(ts.get("relevance_score", 0))
                    sc = float(ts.get("ticker_sentiment_score", 0))
                    if best is None or rel > best[0]:
                        best = (rel, sc)
                except (TypeError, ValueError):
                    pass
        if not hints:
            continue
        out.append(Article(
            source="alphavantage",
            url=item.get("url", ""),
            title=item.get("title", ""),
            body=item.get("summary", ""),
            published_utc=pub,
            tickers_hint=hints,
            baseline_sentiment=best[1] if best else None,
        ))
    print(f"[sources] alphavantage: {len(out)} articles")
    return out


def _av_call(key: str, extra_params: dict) -> list | None:
    """One AV NEWS_SENTIMENT call. Returns the feed list, or None on any
    failure — logging the RAW response body so future issues are diagnosable
    instead of just showing the generic top-level error message."""
    params = {"function": "NEWS_SENTIMENT", "apikey": key, **extra_params}
    try:
        r = requests.get("https://www.alphavantage.co/query", params=params,
                         timeout=config.HTTP_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except Exception as exc:
        print(f"[sources] alphavantage request error: {exc}")
        return None

    feed = data.get("feed")
    if feed is None:
        note = data.get("Information") or data.get("Note") or data.get("Error Message") or data
        print(f"[sources] alphavantage no feed (params={list(extra_params.keys())}): {note}")
        return None
    return feed


# --------------------------------------------------------------------------
# Benzinga  (premium)
# --------------------------------------------------------------------------
def fetch_benzinga(key: str, lookback_hours: int) -> list[Article]:
    if not key:
        print("[sources] BENZINGA_API_KEY missing -> skipping Benzinga (premium)")
        return []
    since = _utc_now() - dt.timedelta(hours=lookback_hours)
    try:
        r = requests.get(
            "https://api.benzinga.com/api/v2/news",
            params={
                "token": key,
                "tickers": ",".join(_equity_universe()),
                "displayOutput": "full",
                "pageSize": 100,
            },
            headers={"accept": "application/json"},
            timeout=config.HTTP_TIMEOUT,
        )
        r.raise_for_status()
        items = r.json()
    except Exception as exc:
        print(f"[sources] benzinga error: {exc}")
        return []

    out: list[Article] = []
    for item in items or []:
        try:
            pub = dt.datetime.fromtimestamp(int(item.get("created", 0)), tz=dt.timezone.utc)
        except (TypeError, ValueError):
            pub = _utc_now()
        if pub < since:
            continue
        stocks = [s.get("name") for s in item.get("stocks", []) if s.get("name") in config.UNIVERSE]
        if not stocks:
            continue
        out.append(Article(
            source="benzinga",
            url=item.get("url", ""),
            title=item.get("title", ""),
            body=item.get("teaser", "") or item.get("body", ""),
            published_utc=pub,
            tickers_hint=stocks,
        ))
    print(f"[sources] benzinga: {len(out)} articles")
    return out


# --------------------------------------------------------------------------
# Dispatcher
# --------------------------------------------------------------------------
def fetch_all(secrets, tier: config.TierSpec, lookback_hours: int) -> list[Article]:
    articles: list[Article] = []
    if "finnhub" in tier.sources:
        articles += fetch_finnhub(secrets.finnhub_key, lookback_hours)
    if "alphavantage" in tier.sources:
        articles += fetch_alphavantage(secrets.alphavantage_key, lookback_hours)
    if "benzinga" in tier.sources:
        articles += fetch_benzinga(secrets.benzinga_key, lookback_hours)
    print(f"[sources] total raw: {len(articles)} articles ({tier.name} tier)")
    return articles
