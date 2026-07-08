# market_brief/classify/triage.py — market_brief_v2.0.0
"""
Stage 1 of the cascade — Haiku triage, PER TICKER.

The universe is fetched per-ticker (Finnhub /company-news per symbol), so we
already know which name each headline belongs to. Rather than re-derive the
ticker for hundreds of clusters, we hand Haiku ONE ticker and its recent
headlines and ask for the NET market impact for THAT name:
  - sentiment  (-1.0 .. +1.0)
  - magnitude  ( 0.0 .. 1.0 : 0 = routine/no real news, 1 = major mover)
  - event_type (bucket driving the decay half-life)
  - one_line   (why it matters)

Runs on EVERY tier (free = this only). Output gates escalation to Sonnet.

v2.0.0 — 2026-07-08 — per-ticker triage (was per-cluster triage_event); ticker
         is known, so no ticker extraction — just judge its news.
"""

from __future__ import annotations

from typing import Any

import config
from classify.llm_client import LLMClient

_EVENT_TYPES = list(config.HALF_LIFE_HOURS.keys())

_SYSTEM = (
    "You are a fast financial-news triage classifier for an options trading "
    "desk. You are given ONE ticker and its recent headlines; judge the NET "
    "market impact for THAT ticker today. You are terse and calibrated, "
    "skeptical of routine or priced-in news. Reply with JSON only, no prose."
)


def _user_prompt(ticker: str, headlines: str, hint: str) -> str:
    return f"""TICKER: {ticker}

EVENT_TYPES (pick the single best): {', '.join(_EVENT_TYPES)}

Baseline provider sentiment hint (may be empty/noisy): {hint or 'none'}

RECENT HEADLINES for {ticker}:
{headlines}

Judge the NET, market-moving impact for {ticker} across these headlines and
return JSON:
{{
  "sentiment": <float -1.0..1.0, impact direction>,
  "magnitude": <float 0.0..1.0, 0=routine/no real news, 1=major mover>,
  "event_type": "<one of EVENT_TYPES>",
  "one_line": "<<=15 word why-it-matters, empty if nothing material>"
}}
If there is no material, market-moving news for {ticker}, return magnitude 0."""


def triage_ticker(
    client: LLMClient,
    model: str,
    ticker: str,
    headlines: str,
    baseline_hint: str = "",
) -> dict[str, Any]:
    raw = client.json_call(
        model=model,
        system=_SYSTEM,
        user=_user_prompt(ticker, headlines, baseline_hint),
        max_tokens=400,
    )
    return _sanitize(raw)


def _sanitize(raw: Any) -> dict[str, Any]:
    """Never trust raw model output — clamp and whitelist."""
    if not isinstance(raw, dict):
        return {"sentiment": 0.0, "magnitude": 0.0,
                "event_type": "GENERAL", "one_line": ""}
    try:
        sent = max(-1.0, min(1.0, float(raw.get("sentiment", 0.0))))
    except (TypeError, ValueError):
        sent = 0.0
    try:
        mag = max(0.0, min(1.0, float(raw.get("magnitude", 0.0))))
    except (TypeError, ValueError):
        mag = 0.0
    et = raw.get("event_type", "GENERAL")
    if et not in config.HALF_LIFE_HOURS:
        et = "GENERAL"
    one = str(raw.get("one_line", ""))[:120]
    return {"sentiment": sent, "magnitude": mag, "event_type": et, "one_line": one}
