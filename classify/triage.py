# market_brief/classify/triage.py — market_brief_v1.0.0
"""
Stage 1 of the cascade — Haiku triage.

For a clustered event, extract cheaply and fast:
  - which in-universe tickers are DIRECTLY implicated
  - sentiment  (-1.0 .. +1.0)
  - magnitude  ( 0.0 .. 1.0 : routine vs genuinely market-moving)
  - event_type (bucket driving the decay half-life)

Runs on EVERY tier (free = this only). Output gates escalation to Sonnet.

Last updated: 2026-07-04
"""

from __future__ import annotations

import json
from typing import Any

import config
from classify.llm_client import LLMClient

_EVENT_TYPES = list(config.HALF_LIFE_HOURS.keys())

_SYSTEM = (
    "You are a fast financial-news triage classifier for an options trading "
    "desk. You tag news to a FIXED universe of tickers and score it. You are "
    "terse, calibrated, and you never invent tickers outside the provided "
    "universe. Reply with JSON only, no prose."
)


def _user_prompt(title: str, body: str, universe: list[str], hint: str) -> str:
    return f"""UNIVERSE (only tag from this list): {', '.join(universe)}

EVENT_TYPES (pick the single best): {', '.join(_EVENT_TYPES)}

Baseline provider hint (may be empty/noisy): {hint or 'none'}

HEADLINE: {title}
BODY: {body[:1500]}

Return JSON:
{{
  "tickers": ["<direct mentions from UNIVERSE only>"],
  "sentiment": <float -1.0..1.0, market impact direction>,
  "magnitude": <float 0.0..1.0, 0=routine/noise, 1=major mover>,
  "event_type": "<one of EVENT_TYPES>",
  "one_line": "<<=15 word why-it-matters>"
}}
If no universe ticker is implicated, return "tickers": []."""


def triage_event(
    client: LLMClient,
    model: str,
    title: str,
    body: str,
    baseline_hint: str = "",
    universe: list[str] | None = None,
) -> dict[str, Any]:
    universe = universe or config.UNIVERSE
    raw = client.json_call(
        model=model,
        system=_SYSTEM,
        user=_user_prompt(title, body, universe, baseline_hint),
        max_tokens=400,
    )
    return _sanitize(raw, universe)


def _sanitize(raw: Any, universe: list[str]) -> dict[str, Any]:
    """Never trust raw model output — clamp and whitelist."""
    if not isinstance(raw, dict):
        return {"tickers": [], "sentiment": 0.0, "magnitude": 0.0,
                "event_type": "GENERAL", "one_line": ""}
    uni = set(universe)
    tickers = [t for t in raw.get("tickers", []) if isinstance(t, str) and t in uni]
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
    return {"tickers": tickers, "sentiment": sent, "magnitude": mag,
            "event_type": et, "one_line": one}
