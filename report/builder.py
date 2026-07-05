# market_brief/report/builder.py — market_brief_v1.1.1
"""
Report builder — the deliverable read at 09:15 ET.

Structure:
  1. BLUF: top 4-5 tickers ranked by composite (blended w/ surprise on
     mid/premium). Ranked names are TAGGED if they report earnings this week.
  2. TODAY'S LANDMINES (macro), split by timing:
       - ALREADY OUT (pre-open, actuals in -> surprise knowable)
       - STILL AHEAD (~10:00 ET / ~14:00 ET; FOMC statement + presser)
     Macro is its own tier, never summed into ticker scores.
  3. EARNINGS THIS WEEK for watched names (date + BMO/AMC + typical time).
  4. Per-ticker detail.

Tier is visible on purpose — the granularity climb IS the product ladder.
Calendar facts (macro timing, earnings) appear on ALL tiers; the LLM-driven
depth (surprise, spillover reasoning, validation) is what escalates.

Returns (markdown_text, bluf_records) so main.py can also emit JSON.

Last updated: 2026-07-04
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import config
from data import macro_cal
from data.earnings_cal import EarningsEvent, by_symbol as earnings_by_symbol

_ARROW = {"BULLISH": "🟢▲", "BEARISH": "🔴▼", "NEUTRAL": "⚪️•"}
_BADGE = {"free": "FREE", "mid": "MID", "premium": "PREMIUM"}
_SESS_SHORT = {"bmo": "BMO", "amc": "AMC", "dmh": "DMH", "unknown": "TBD"}


def _earn_tag(ev: EarningsEvent, today: dt.date) -> str:
    day = "TODAY" if ev.date == today else ev.date.strftime("%a")
    return f"📅 {day} {_SESS_SHORT.get(ev.session, 'TBD')}"


def build_report(
    composites: list,
    macro_events: list,                 # list[macro_cal.MacroEvent]
    earnings_events: list,              # list[EarningsEvent]
    tier: config.TierSpec,
    report_dt_et: dt.datetime,
    validation_stats: dict[str, Any] | None = None,
    source_counts: dict[str, int] | None = None,
) -> tuple[str, list[dict[str, Any]]]:

    today = report_dt_et.date()
    earn_map = earnings_by_symbol(earnings_events)

    lines: list[str] = []
    lines.append(f"*VERTIGO CAPITAL PRE-MARKET BRIEF* — {report_dt_et.strftime('%a %b %d, %Y')}")
    lines.append(f"_09:15 ET rollup · tier: {_BADGE[tier.name]}_")
    if macro_cal.is_fomc_day(macro_events):
        lines.append("🏛️ *FED DAY* — FOMC decision 2:00pm ET, presser 2:30pm ET.")
    lines.append("")

    # ---- BLUF -----------------------------------------------------------
    lines.append("*BOTTOM LINE — LOOK HERE FIRST*")
    top = composites[:5]
    bluf_records: list[dict[str, Any]] = []
    if not top:
        lines.append("_No actionable single-name signal since last report._")
    for i, c in enumerate(top, 1):
        seg = f"{i}. {_ARROW[c.direction]} *{c.ticker}*  score `{c.score:+.2f}`"
        if tier.surprise_term and c.surprise_delta is not None:
            seg += f"  Δ`{c.surprise_delta:+.2f}`"
        seg += f"  conv `{c.conviction:.2f}`"
        ev = earn_map.get(c.ticker)
        if ev:
            seg += f"  {_earn_tag(ev, today)}"
        lines.append(seg)
        bluf_records.append({
            "rank": i, "ticker": c.ticker, "direction": c.direction,
            "score": round(c.score, 4), "surprise_delta": c.surprise_delta,
            "conviction": c.conviction, "n_signals": c.n_signals,
            "earnings_this_week": (
                {"date": ev.date.isoformat(), "session": ev.session} if ev else None),
        })
    if any(r["earnings_this_week"] for r in bluf_records):
        lines.append("_⚠ 📅-tagged names report this week: earnings regime "
                     "(IV crush / binary) — size accordingly, not on sentiment alone._")
    lines.append("")

    # ---- LANDMINES (macro, split by timing) -----------------------------
    lines.append("*TODAY'S LANDMINES (macro)*")
    already_out, ahead = macro_cal.split_by_timing(macro_events)
    if not macro_events:
        lines.append("• None scheduled / calendar unavailable.")
    else:
        if already_out:
            lines.append("_Already out (pre-open):_")
            for m in already_out[:6]:
                extra = _macro_extra(m)
                lines.append(f"  • {_tier_tag(m.magnitude)} *{m.label}* — {m.et_clock}{extra}")
        if ahead:
            lines.append("_Still ahead (post-open):_")
            for m in ahead[:6]:
                extra = _macro_extra(m)
                lines.append(f"  • {_tier_tag(m.magnitude)} *{m.label}* — {m.et_clock}{extra}")
        lines.append("_On high-impact macro days, single-name sentiment is less "
                     "reliable (everything correlates)._")
    lines.append("")

    # ---- EARNINGS THIS WEEK --------------------------------------------
    lines.append("*EARNINGS THIS WEEK (watched names)*")
    if not earnings_events:
        lines.append("• None among watched names / calendar unavailable.")
    else:
        for ev in earnings_events[:12]:
            when = "TODAY" if ev.date == today else ev.date.strftime("%a %b %-d")
            est = f", est EPS {ev.eps_estimate:.2f}" if ev.eps_estimate is not None else ""
            lines.append(f"• *{ev.symbol}* — {when}, {ev.session_label} "
                         f"(call {ev.typical_time}, typical){est}")
        lines.append("_Times are the typical session slot; exact call time may vary._")
    lines.append("")

    # ---- DETAIL ---------------------------------------------------------
    lines.append("*SUPPORTING DETAIL*")
    if not composites:
        lines.append("_Nothing to expand._")
    for c in composites[:10]:
        head = f"*{c.ticker}* {_ARROW[c.direction]} `{c.score:+.2f}`"
        meta = f"{c.n_direct} direct"
        if c.n_spill:
            meta += f", {c.n_spill} spillover"
        if tier.surprise_term and c.surprise_delta is not None:
            meta += f", Δ{c.surprise_delta:+.2f}"
        ev = earn_map.get(c.ticker)
        tag = f"  {_earn_tag(ev, today)}" if ev else ""
        lines.append(f"{head}  ({meta}){tag}")
        for r in c.reasons:
            lines.append(f"   – {r}")
    lines.append("")

    # ---- PREMIUM FOOTER -------------------------------------------------
    if tier.validation and validation_stats:
        lines.append("*SIGNAL VALIDATION (trailing)*")
        hr, n = validation_stats.get("hit_rate"), validation_stats.get("n", 0)
        if hr is not None and n:
            lines.append(f"• Directional hit-rate: {hr:.0%} over {n} scored signals")
        else:
            lines.append("• Building validation history (need forward-move data).")
        lines.append("")

    if source_counts and tier.name == "premium":
        cov = ", ".join(f"{k}:{v}" for k, v in sorted(source_counts.items()))
        lines.append(f"_sources — {cov}_")

    return "\n".join(lines).strip(), bluf_records


def _tier_tag(mag: float) -> str:
    if mag >= 0.85:
        return "🟥 T1"
    if mag >= 0.6:
        return "🟧 T2"
    return "🟨 T3"


def _macro_extra(m) -> str:
    if m.actual and m.forecast:
        return f"  (actual {m.actual} vs est {m.forecast})"
    if m.forecast:
        return f"  (est {m.forecast})"
    return ""
