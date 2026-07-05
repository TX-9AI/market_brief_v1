# market_brief/score/aggregate.py — market_brief_v1.0.0
"""
Aggregation — collapse many signals into one composite per ticker.

composite(ticker) = sum over signals of
        sentiment * magnitude * weight * decay(age, event_type)

  - decay half-life is PER EVENT TYPE (config.HALF_LIFE_HOURS), not global.
  - direct mentions already carry more weight than spillover (set upstream).
  - macro is NOT summed in here — it lives in its own landmines section.

Surprise term (mid/premium only): delta of today's composite vs a trailing
baseline. A name that just FLIPPED hard is more actionable than one that's
been mildly positive all week — surprise catches that.

Last updated: 2026-07-04
"""

from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass, field
from typing import Any

import config


@dataclass
class TickerComposite:
    ticker: str
    score: float                       # signed composite
    direction: str                     # BULLISH / BEARISH / NEUTRAL
    n_signals: int
    n_direct: int
    n_spill: int
    conviction: float                  # 0..1, magnitude-weighted coverage
    surprise_delta: float | None = None
    reasons: list[str] = field(default_factory=list)   # one-liners, ranked

    @property
    def rank_key(self) -> float:
        base = abs(self.score)
        if self.surprise_delta is not None:
            base = 0.7 * base + 0.3 * abs(self.surprise_delta)
        return base


def _decay(age_hours: float, event_type: str) -> float:
    hl = config.HALF_LIFE_HOURS.get(event_type, config.DEFAULT_HALF_LIFE)
    return 0.5 ** (max(0.0, age_hours) / hl)


def compute_composites(
    records: list[dict[str, Any]],
    now: dt.datetime,
    tier: config.TierSpec,
    trailing_baseline: dict[str, float] | None = None,
) -> list[TickerComposite]:
    """
    records: rows with keys
        ticker, sentiment, magnitude, weight, event_type,
        is_spillover, created_utc (aware datetime), one_line
    """
    trailing_baseline = trailing_baseline or {}
    buckets: dict[str, dict[str, Any]] = {}

    for r in records:
        t = r["ticker"]
        age_h = (now - r["created_utc"]).total_seconds() / 3600.0
        decay = _decay(age_h, r.get("event_type", "GENERAL"))
        contrib = r["sentiment"] * r["magnitude"] * r["weight"] * decay

        b = buckets.setdefault(t, {
            "score": 0.0, "mag": 0.0, "n": 0, "direct": 0, "spill": 0,
            "reasons": [],
        })
        b["score"] += contrib
        b["mag"] += r["magnitude"] * r["weight"] * decay
        b["n"] += 1
        if r.get("is_spillover"):
            b["spill"] += 1
        else:
            b["direct"] += 1
        ol = (r.get("one_line") or "").strip()
        if ol:
            b["reasons"].append((abs(contrib), ol))

    out: list[TickerComposite] = []
    for t, b in buckets.items():
        score = b["score"]
        direction = "BULLISH" if score > 0.05 else "BEARISH" if score < -0.05 else "NEUTRAL"
        conviction = 1.0 - math.exp(-b["mag"])   # saturating 0..1
        reasons = [msg for _, msg in sorted(b["reasons"], reverse=True)[:3]]

        surprise = None
        if tier.surprise_term:
            surprise = score - trailing_baseline.get(t, 0.0)

        out.append(TickerComposite(
            ticker=t, score=score, direction=direction,
            n_signals=b["n"], n_direct=b["direct"], n_spill=b["spill"],
            conviction=round(conviction, 3),
            surprise_delta=(round(surprise, 4) if surprise is not None else None),
            reasons=reasons,
        ))

    out.sort(key=lambda c: c.rank_key, reverse=True)
    return out
