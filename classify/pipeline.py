# market_brief/classify/pipeline.py — market_brief_v2.0.0
"""
The cascade orchestrator — turns per-ticker news into weighted SIGNAL rows,
gated entirely by the active tier.

    free    : Haiku triage per ticker. Spillover = static flat discount.
    mid     : Haiku triage -> Sonnet on tickers clearing SONNET_MAGNITUDE_FLOOR.
              Real ISOLATED/SECTOR reasoning + peer expansion.
    premium : Haiku triage -> Sonnet on EVERY ticker with news.

Design (v2): the news feed is fetched PER TICKER (Finnhub /company-news per
symbol), so we group articles by name and make ONE model call per ticker with
its recent headlines — the ~29 names run CONCURRENTLY. This replaces the old
"dedup into hundreds of cross-ticker clusters, then one call per cluster"
middle, which turned a loud news morning into hundreds of serial API calls.

A "signal" is one (ticker, sentiment, magnitude, weight, ...) tuple. Direct
signals get DIRECT_MENTION_WEIGHT; sector spillover gets the discounted
SECTOR_SPILLOVER_WEIGHT. Per-ticker article count adds a saturating coverage
bonus. The Signal shape is unchanged, so db / aggregate / report / intraday
all consume it exactly as before.

v2.0.0 — 2026-07-08 — per-ticker classify (classify_by_ticker) replacing the
         per-cluster cascade (classify_clusters). dedup is no longer used.
"""

from __future__ import annotations

import hashlib
import math
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from typing import Any

import config
from classify import peer_map, triage as triage_mod, scope as scope_mod
from classify.llm_client import LLMClient

# forward ref only for typing; avoids importing data.sources at module load
try:  # pragma: no cover
    from data.sources import Article
except Exception:  # pragma: no cover
    Article = Any  # type: ignore


@dataclass
class Signal:
    ticker: str
    sentiment: float
    magnitude: float
    weight: float                 # mention/spillover * coverage
    event_type: str
    scope: str                    # ISOLATED | SECTOR | SPILL
    is_spillover: bool
    model_used: str
    confidence: float
    cluster_id: int | None        # stable id per (ticker, lead headline)
    one_line: str = ""
    rationale: str = ""


# how many headlines to hand the model per ticker (bounds prompt size)
_MAX_HEADLINES = 12
_UNIVERSE = set(config.UNIVERSE)


def _coverage_bonus(article_count: int) -> float:
    """Saturating coverage weight: a name with broad wire pickup gets a slightly
    higher weight than a single-source mention."""
    capped = min(article_count, config.CLUSTER_SIZE_CAP)
    return 1.0 + 0.15 * math.log1p(capped - 1) if capped > 1 else 1.0


def _digest(arts: list) -> str:
    """Compact, bounded headline digest for one ticker: most-recent / richest
    first, each 'HEADLINE — summary(trimmed)'."""
    ordered = sorted(arts, key=lambda a: (a.published_utc, len(a.body)), reverse=True)
    lines = []
    for a in ordered[:_MAX_HEADLINES]:
        body = (a.body or "").strip().replace("\n", " ")
        line = a.title.strip()
        if body:
            line += f" — {body[:200]}"
        lines.append(f"- {line}")
    return "\n".join(lines)


def _baseline_hint(arts: list) -> str:
    vals = [a.baseline_sentiment for a in arts if a.baseline_sentiment is not None]
    if not vals:
        return ""
    return f"avg provider sentiment {sum(vals) / len(vals):+.2f} over {len(vals)} tagged items"


def _cluster_id(ticker: str, digest: str) -> int:
    """Stable 31-bit id per (ticker, lead headline) so intraday dedup fires once
    per distinct story but re-alerts on a genuinely new lead."""
    lead = digest.split("\n", 1)[0]
    h = hashlib.sha1(f"{ticker}|{lead}".encode()).hexdigest()[:8]
    return int(h, 16) & 0x7FFFFFFF


def _classify_one_ticker(ticker: str, arts: list, client: LLMClient,
                         tier: config.TierSpec) -> list[Signal]:
    digest = _digest(arts)
    tri = triage_mod.triage_ticker(
        client, tier.triage_model, ticker, digest, _baseline_hint(arts))

    # nothing material -> no signal for this name
    if tri["magnitude"] <= 0.0 and abs(tri["sentiment"]) < 1e-6:
        return []

    cov = _coverage_bonus(len(arts))
    model_used = tier.triage_model
    sent, mag = tri["sentiment"], tri["magnitude"]
    conf, scope_label, rationale = 0.5, "ISOLATED", ""
    spill_tickers: list[str] = []

    do_deep = tier.deep_model is not None and (
        tier.deep_on_everything or mag >= config.SONNET_MAGNITUDE_FLOOR)

    if do_deep:
        deep = scope_mod.deep_assess_ticker(
            client, tier.deep_model, ticker, digest, tri)
        model_used = tier.deep_model
        sent, mag, conf = deep["sentiment"], deep["magnitude"], deep["confidence"]
        scope_label, rationale = deep["scope"], deep["rationale"]
        spill_tickers = deep["spillover_tickers"] if tier.llm_spillover else []
    elif not tier.llm_spillover and mag >= 0.6:
        # free tier: cheap static flat spillover on strong single-name news
        spill_tickers = sorted(set(peer_map.peers_for(ticker)) - {ticker})

    cid = _cluster_id(ticker, digest)
    out = [Signal(
        ticker=ticker, sentiment=sent, magnitude=mag,
        weight=config.DIRECT_MENTION_WEIGHT * cov,
        event_type=tri["event_type"], scope=scope_label,
        is_spillover=False, model_used=model_used, confidence=conf,
        cluster_id=cid, one_line=tri["one_line"], rationale=rationale,
    )]
    for pt in spill_tickers:
        out.append(Signal(
            ticker=pt, sentiment=sent, magnitude=mag,
            weight=config.SECTOR_SPILLOVER_WEIGHT * cov,
            event_type=tri["event_type"], scope="SPILL",
            is_spillover=True, model_used=model_used, confidence=conf * 0.8,
            cluster_id=cid, one_line=tri["one_line"], rationale=rationale,
        ))
    return out


def classify_by_ticker(
    articles: list,
    client: LLMClient,
    tier: config.TierSpec,
) -> list[Signal]:
    """Group articles by universe ticker, classify each name ONCE (Haiku, with a
    per-tier Sonnet escalation), running the names concurrently. Returns a flat
    list of Signal rows — same shape the rest of the pipeline already consumes."""
    by_ticker: dict[str, list] = {}
    for a in articles:
        for t in (getattr(a, "tickers_hint", None) or ()):
            if t in _UNIVERSE:
                by_ticker.setdefault(t, []).append(a)

    tickers = sorted(by_ticker)
    print(f"[classify] {len(tickers)} tickers with news from {len(articles)} "
          f"articles ({tier.name} tier, ≤{config.LLM_MAX_WORKERS} concurrent)")
    if not tickers:
        return []

    signals: list[Signal] = []
    workers = max(1, min(config.LLM_MAX_WORKERS, len(tickers)))
    with ThreadPoolExecutor(max_workers=workers) as ex:
        futures = [ex.submit(_classify_one_ticker, t, by_ticker[t], client, tier)
                   for t in tickers]
        for fut in futures:
            try:
                signals.extend(fut.result())
            except Exception as exc:   # one bad ticker never sinks the run
                print(f"[classify] ticker classify error: {exc}")

    return signals
