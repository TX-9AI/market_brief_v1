# market_brief/report/emit.py — market_brief_v1.3.0
"""
Machine-readable emit of the finished brief.

Writes report.json in the shape day_trader_pro/selector.py consumes: a flat
{ticker: score} map for quick ranking, plus a richer per-ticker array and the
macro/earnings context so the selection model can reason with full information.

This is the ONLY coupling point between the two projects. The brief still runs
and delivers to Telegram exactly as before; this just drops a JSON sidecar the
control server reads at ~09:17.

Wire-in (one line in market_brief main.py, right after build_report(...)):

    from report import emit
    emit.emit_report(composites, macro_events, earnings_events, report_dt_et)

Output path resolution (first that is set):
    1. explicit path= argument
    2. $DTP_REPORT_JSON        <- set this on the reporter so both projects agree
    3. ./report.json           (next to the brief; fallback)

v1.3.0 — 2026-07-15 — add `move_ranked` sidecar: pre-market top-8 by
         move-probability (catalyst + event pressure + conviction) for
         day_trader_pro's exactly-8 discretionary wake and the bot's signed
         setup-score nudge. Pure addition — scores/tickers/Telegram unchanged.
Last updated: 2026-07-15
"""

from __future__ import annotations

import datetime as dt
import json
import os
from typing import Any

# Optional: reuse the brief's macro helpers for timing/FOMC. Degrade gracefully
# if the import shape differs so emit never breaks the morning run.
try:
    from data import macro_cal  # type: ignore
except Exception:  # noqa: BLE001
    macro_cal = None


def _default_path() -> str:
    env = os.environ.get("DTP_REPORT_JSON")
    if env:
        return env
    return os.path.join(os.getcwd(), "report.json")


def _g(obj, name, default=None):
    """Safe attribute OR dict-key getter (composites may be either)."""
    if isinstance(obj, dict):
        return obj.get(name, default)
    return getattr(obj, name, default)


def _move_ranked(tickers, earn_today_syms, fomc, landmines, top_n=8):
    """v1.3 — pre-market MOVE-PROBABILITY ranking for day_trader_pro selection.

    "Likely to see a move at the RTH open" — a blend, from fields the brief
    already computes, of: directional catalyst strength (|signed composite|),
    event pressure (earnings TODAY, macro landmines still ahead, FOMC), and
    conviction/coverage. NOT a volume forecast — an expected-motion prior.

    Returns up to top_n dicts: {ticker, strength (0..1 normalized to #1),
    raw, direction, why[]}. day_trader_pro ranks/selects on this; the bot's
    setup_scorer applies a signed ±cap nudge keyed on `strength`.
    """
    # macro pressure is market-wide (indices/rate names feel it most); a single
    # scalar we fold into every name's event term.
    ahead = [m for m in landmines if not m.get("already_out")]
    macro_pressure = min(1.0, 0.5 * len(ahead) + (0.5 if fomc else 0.0))

    raw = []
    for t in tickers:
        tk = t.get("ticker")
        if not tk:
            continue
        catalyst = abs(float(t.get("score") or 0.0))          # signed-composite magnitude
        conv     = float(t.get("conviction") or 0.0)          # 0..1 coverage
        event    = 0.0
        why = []
        if tk in earn_today_syms:
            event = max(event, 1.0); why.append("earnings today")
        elif t.get("earnings_this_week"):
            event = max(event, 0.5); why.append("earnings this week")
        if macro_pressure > 0:
            event = max(event, macro_pressure)
            if fomc: why.append("FOMC day")
            elif ahead: why.append("macro landmine ahead")
        if catalyst > 0:
            why.append(f"catalyst {t.get('direction','NEUTRAL').lower()}")
        # blend — catalyst-led, event pressure second, conviction third
        move = 0.5 * catalyst + 0.3 * event + 0.2 * conv
        raw.append({"ticker": tk, "raw": round(move, 4),
                    "direction": t.get("direction", "NEUTRAL"), "why": why})

    raw.sort(key=lambda r: r["raw"], reverse=True)
    top = raw[:top_n]
    peak = top[0]["raw"] if top and top[0]["raw"] > 0 else 1.0
    for r in top:
        # normalize to #1 == 1.0; floor keeps the 8th meaningfully weighted
        r["strength"] = round(max(0.15, r["raw"] / peak), 3) if peak > 0 else 0.15
    return top


def build_report_dict(
    composites: list,
    macro_events: list,
    earnings_events: list,
    report_dt_et: dt.datetime,
) -> dict[str, Any]:
    today = report_dt_et.date()

    # --- per-ticker -------------------------------------------------------
    scores: dict[str, float] = {}
    tickers: list[dict[str, Any]] = []
    for c in composites:
        tk = _g(c, "ticker")
        if not tk:
            continue
        score = _g(c, "score", 0.0)
        try:
            score = round(float(score), 4)
        except (TypeError, ValueError):
            score = 0.0
        scores[tk] = abs(score)  # magnitude for ranking; signed value kept below
        tickers.append({
            "ticker": tk,
            "score": score,
            "direction": _g(c, "direction", "NEUTRAL"),
            "conviction": _g(c, "conviction", None),
            "surprise_delta": _g(c, "surprise_delta", None),
            "n_signals": _g(c, "n_signals", None),
        })

    # --- earnings ---------------------------------------------------------
    earn_week: list[dict[str, Any]] = []
    earn_today: list[dict[str, Any]] = []
    for ev in earnings_events or []:
        sym = _g(ev, "symbol")
        edate = _g(ev, "date")
        sess = _g(ev, "session", "unknown")
        rec = {
            "symbol": sym,
            "date": edate.isoformat() if hasattr(edate, "isoformat") else str(edate),
            "session": sess,
        }
        earn_week.append(rec)
        if edate == today:
            earn_today.append(rec)
    earn_syms = {r["symbol"] for r in earn_week}
    for t in tickers:
        t["earnings_this_week"] = t["ticker"] in earn_syms

    # --- macro / landmines ------------------------------------------------
    already_out, ahead = [], []
    if macro_cal is not None and macro_events:
        try:
            already_out, ahead = macro_cal.split_by_timing(macro_events)
        except Exception:  # noqa: BLE001
            already_out, ahead = [], list(macro_events)
    else:
        ahead = list(macro_events or [])

    def _macro(m, out_flag):
        return {
            "label": _g(m, "label"),
            "time": _g(m, "et_clock"),
            "magnitude": _g(m, "magnitude"),
            "actual": _g(m, "actual"),
            "forecast": _g(m, "forecast"),
            "already_out": out_flag,
        }

    landmines = [_macro(m, True) for m in already_out] + \
                [_macro(m, False) for m in ahead]

    fomc = False
    if macro_cal is not None:
        try:
            fomc = bool(macro_cal.is_fomc_day(macro_events))
        except Exception:  # noqa: BLE001
            fomc = False

    earn_today_syms = {r["symbol"] for r in earn_today}
    move_ranked = _move_ranked(tickers, earn_today_syms, fomc, landmines, top_n=8)

    return {
        "date": today.isoformat(),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "fomc_day": fomc,
        "scores": scores,
        "tickers": tickers,
        "move_ranked": move_ranked,
        "landmines": landmines,
        "earnings_today": earn_today,
        "notes": (
            "scores map is signal magnitude (for ranking); tickers[].score is "
            "signed (+bullish / -bearish) with direction. Weigh conviction and "
            "event risk in landmines."
        ),
    }


def emit_report(
    composites: list,
    macro_events: list,
    earnings_events: list,
    report_dt_et: dt.datetime,
    path: str | None = None,
) -> str:
    """Build and atomically write report.json. Returns the path written."""
    report = build_report_dict(composites, macro_events, earnings_events,
                               report_dt_et)
    out = path or _default_path()
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    tmp = out + ".tmp"
    with open(tmp, "w") as fh:
        json.dump(report, fh, indent=2)
    os.replace(tmp, out)  # atomic — control never reads a half-written file
    return out
