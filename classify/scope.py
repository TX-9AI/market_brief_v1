# market_brief/classify/scope.py — market_brief_v1.0.0
"""
Stage 2 of the cascade — Sonnet deep pass.

Only runs on mid/premium, and (mid) only for events that cleared the
magnitude floor. Adds the reasoning Haiku is shallow on:
  - refined magnitude (is this really a mover, or priced-in noise?)
  - scope: ISOLATED (company-specific) vs SECTOR (name the sector)
  - spillover decision (LLM says "spills?"; peer_map supplies WHO)
  - confidence

The peer ENUMERATION stays deterministic (peer_map). Sonnet decides only
whether spillover applies and which sector.

Last updated: 2026-07-04
"""

from __future__ import annotations

from typing import Any

import config
from classify import peer_map
from classify.llm_client import LLMClient

_SYSTEM = (
    "You are a senior sell-side analyst assessing whether a news event is "
    "company-specific or sector-wide, and how market-moving it truly is for "
    "an options desk. You are skeptical of routine/priced-in news and you "
    "distinguish signal from wire noise. Reply with JSON only, no prose."
)

_KNOWN_SECTORS = ", ".join(config.SECTORS.keys())


def _user_prompt(title: str, body: str, tickers: list[str], et: str) -> str:
    return f"""Direct tickers already identified: {', '.join(tickers) or 'none'}
Event type: {et}
Known sectors (use these labels if SECTOR): {_KNOWN_SECTORS}

HEADLINE: {title}
BODY: {body[:2500]}

Assess and return JSON:
{{
  "magnitude": <float 0.0..1.0, refined true market impact>,
  "sentiment": <float -1.0..1.0, refined>,
  "scope": "ISOLATED" | "SECTOR",
  "sector": "<one known-sector label if scope==SECTOR, else empty>",
  "spills_over": <true only if peers plausibly move materially>,
  "confidence": <float 0.0..1.0>,
  "rationale": "<<=25 words, the actual mechanism>"
}}"""


def deep_assess(
    client: LLMClient,
    model: str,
    title: str,
    body: str,
    triage: dict[str, Any],
) -> dict[str, Any]:
    raw = client.json_call(
        model=model,
        system=_SYSTEM,
        user=_user_prompt(title, body, triage["tickers"], triage["event_type"]),
        max_tokens=500,
    )
    return _sanitize(raw, triage)


def _sanitize(raw: Any, triage: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(raw, dict):
        # fall back to triage numbers, no spillover
        return {"magnitude": triage["magnitude"], "sentiment": triage["sentiment"],
                "scope": "ISOLATED", "sector": None, "spills_over": False,
                "confidence": 0.4, "rationale": "", "spillover_tickers": []}

    def _clamp(v, lo, hi, dflt):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return dflt

    mag = _clamp(raw.get("magnitude"), 0.0, 1.0, triage["magnitude"])
    sent = _clamp(raw.get("sentiment"), -1.0, 1.0, triage["sentiment"])
    conf = _clamp(raw.get("confidence"), 0.0, 1.0, 0.5)
    scope = raw.get("scope", "ISOLATED")
    scope = scope if scope in ("ISOLATED", "SECTOR") else "ISOLATED"
    spills = bool(raw.get("spills_over", False)) and scope == "SECTOR"

    spillover_tickers: list[str] = []
    sector_key = None
    if spills:
        sector_key = peer_map.resolve_sector_name(raw.get("sector", ""))
        if sector_key:
            exclude = set(triage["tickers"])
            spillover_tickers = peer_map.peers_for_sector(sector_key, exclude=exclude)
        else:
            spills = False  # couldn't place the sector -> no spillover

    return {"magnitude": mag, "sentiment": sent, "scope": scope,
            "sector": sector_key, "spills_over": spills,
            "confidence": conf, "rationale": str(raw.get("rationale", ""))[:200],
            "spillover_tickers": spillover_tickers}
