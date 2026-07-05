# market_brief/data/earnings_cal.py — market_brief_v1.1.0
"""
Earnings calendar for the watched universe.

Why this earns its place: an earnings name is a different REGIME, not just
another headline. IV crush + a binary event mean short-dated option
structures behave nothing like they do on a normal day. Knowing a ranked
name reports this week is often the difference between deploying a server on
the sentiment and staying flat into the print.

Source: Finnhub /calendar/earnings (free tier OK). We filter to the equity
subset of config.UNIVERSE (indices/ETFs never report) and to today..Friday
of the current week.

Data honesty: Finnhub reliably gives the SESSION (bmo/amc/dmh); it does not
reliably give an exact call time. We surface the session as truth and add a
TYPICAL time hint, clearly labeled. Exact-time enrichment is a later hook.

Last updated: 2026-07-04
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

import requests

import config

# Universe members that never report earnings — filter them out.
_NON_REPORTING = {
    "SPY", "QQQ", "SPX", "IWM", "DIA", "TLT", "GLD", "SMH",
}

# Session code -> (human label, typical ET call-time hint). Hints are TYPICAL,
# not confirmed — labeled as such in the report.
_SESSION = {
    "bmo": ("pre-open (BMO)", "~8:00am ET"),
    "amc": ("after close (AMC)", "~5:00pm ET"),
    "dmh": ("during market hours", "intraday"),
}


@dataclass
class EarningsEvent:
    symbol: str
    date: dt.date
    session: str              # bmo | amc | dmh | unknown
    eps_estimate: float | None

    @property
    def session_label(self) -> str:
        return _SESSION.get(self.session, ("time unconfirmed", "TBD"))[0]

    @property
    def typical_time(self) -> str:
        return _SESSION.get(self.session, ("", "TBD"))[1]


def _week_bounds(today: dt.date) -> tuple[dt.date, dt.date]:
    """today .. Friday of the current ISO week (never looks backward)."""
    friday = today + dt.timedelta(days=(4 - today.weekday()))
    if friday < today:            # weekend guard -> next Friday
        friday = today + dt.timedelta(days=(4 - today.weekday()) % 7)
    return today, friday


def fetch_earnings(key: str, today: dt.date | None = None) -> list[EarningsEvent]:
    today = today or dt.datetime.now(dt.timezone.utc).date()
    if not key:
        print("[earnings] FINNHUB_API_KEY missing -> earnings calendar skipped")
        return []

    start, end = _week_bounds(today)
    universe = [t for t in config.UNIVERSE if t not in _NON_REPORTING]
    uni_set = set(universe)

    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/earnings",
            params={"from": start.isoformat(), "to": end.isoformat(), "token": key},
            timeout=config.HTTP_TIMEOUT,
        )
        r.raise_for_status()
        rows = (r.json() or {}).get("earningsCalendar", []) or []
    except Exception as exc:
        print(f"[earnings] fetch error: {exc}")
        return []

    out: list[EarningsEvent] = []
    for row in rows:
        sym = row.get("symbol")
        if sym not in uni_set:
            continue
        try:
            d = dt.datetime.strptime(row.get("date", ""), "%Y-%m-%d").date()
        except ValueError:
            continue
        if d < start or d > end:
            continue
        session = str(row.get("hour", "") or "").lower()
        if session not in _SESSION:
            session = "unknown"
        eps = row.get("epsEstimate")
        try:
            eps = float(eps) if eps is not None else None
        except (TypeError, ValueError):
            eps = None
        out.append(EarningsEvent(symbol=sym, date=d, session=session, eps_estimate=eps))

    out.sort(key=lambda e: (e.date, e.symbol))
    print(f"[earnings] {len(out)} watched-name earnings {start}..{end}")
    return out


def by_symbol(events: list[EarningsEvent]) -> dict[str, EarningsEvent]:
    """First (earliest) earnings event per symbol, for ranked-ticker tagging."""
    out: dict[str, EarningsEvent] = {}
    for e in events:
        if e.symbol not in out:
            out[e.symbol] = e
    return out
