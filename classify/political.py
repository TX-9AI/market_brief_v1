# market_brief/classify/political.py — market_brief_v1.0.0
"""
Political-post classification — [platinum].

A Trump post is often macro/broad (tariffs, Powell, China) rather than a
single-ticker story, so this uses a purpose-built prompt distinct from the
company-news triage. It answers: is this market-moving, how hard, which way,
and what does it hit (specific universe tickers, a sector, or BROAD_MARKET)?

Runs on Sonnet (platinum is the top tier — accuracy over cost here). Output
gates the volatility push alert.

Last updated: 2026-07-04
"""

from __future__ import annotations

from typing import Any

import config
from classify import peer_map
from classify.llm_client import LLMClient

_SYSTEM = (
    "You are a macro trading-desk analyst watching political social-media "
    "posts for MARKET IMPACT only. Most posts are political noise and should "
    "score ~0. You react to: tariffs/trade, the Fed/Powell/rates, China, "
    "energy/oil, specific named public companies, tax/regulation, and major "
    "geopolitical escalation. You are calibrated and skeptical. JSON only."
)

_KNOWN_SECTORS = ", ".join(config.SECTORS.keys())


def _user_prompt(text: str) -> str:
    return f"""UNIVERSE tickers: {', '.join(config.UNIVERSE)}
Known sectors: {_KNOWN_SECTORS}

POST:
\"\"\"{text[:1800]}\"\"\"

Return JSON:
{{
  "market_moving": <true/false>,
  "magnitude": <float 0.0..1.0, expected index/vol impact; 0 = noise>,
  "sentiment": <float -1.0..1.0, risk-on(+) vs risk-off(-)>,
  "affected": ["<universe tickers>", "SECTOR:<known-sector>", "BROAD_MARKET"],
  "one_line": "<<=15 words: what it is and why it moves the tape>"
}}
Use BROAD_MARKET for index-wide risk (tariffs, Fed, war). Only list a ticker
if the post plausibly moves that specific name. If pure politics, set
market_moving false and magnitude 0."""


def classify_post(client: LLMClient, model: str, text: str) -> dict[str, Any]:
    raw = client.json_call(model=model, system=_SYSTEM,
                           user=_user_prompt(text), max_tokens=400)
    return _sanitize(raw)


def _sanitize(raw: Any) -> dict[str, Any]:
    if not isinstance(raw, dict):
        return {"market_moving": False, "magnitude": 0.0, "sentiment": 0.0,
                "affected": [], "one_line": "", "tickers": [], "broad": False}

    def _clamp(v, lo, hi, d):
        try:
            return max(lo, min(hi, float(v)))
        except (TypeError, ValueError):
            return d

    mag = _clamp(raw.get("magnitude"), 0.0, 1.0, 0.0)
    sent = _clamp(raw.get("sentiment"), -1.0, 1.0, 0.0)
    moving = bool(raw.get("market_moving", False))

    tickers: list[str] = []
    broad = False
    uni = set(config.UNIVERSE)
    for a in raw.get("affected", []) or []:
        if not isinstance(a, str):
            continue
        if a == "BROAD_MARKET":
            broad = True
        elif a.startswith("SECTOR:"):
            sec = peer_map.resolve_sector_name(a.split(":", 1)[1])
            if sec:
                tickers.extend(config.SECTORS.get(sec, []))
        elif a in uni:
            tickers.append(a)

    return {"market_moving": moving, "magnitude": mag, "sentiment": sent,
            "affected": raw.get("affected", []), "tickers": sorted(set(tickers)),
            "broad": broad, "one_line": str(raw.get("one_line", ""))[:160]}
