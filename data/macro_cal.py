# market_brief/data/macro_cal.py — market_brief_v1.2.0
"""
Macro / "red folder" economic calendar.

Design decisions (by intent):
  - Macro is DETERMINISTIC and known in advance. No LLM ever touches it.
    Magnitude comes from a hand-authored table (you own the tiers).
  - Macro is NOT summed into per-ticker composites. On an FOMC/CPI day,
    single-name idiosyncratic sentiment is LESS reliable — everything
    correlates. Macro is surfaced as its own "TODAY'S LANDMINES" section.

v1.1 adds RELEASE-WINDOW awareness. The 09:15 ET report sits after the 08:30
prints but before the 10:00 / 14:00 ones, so we split:
  - PRE_OPEN  (<= report time): actuals are already knowable -> show surprise
  - MID_MORNING (~10:00 ET) and AFTERNOON (~14:00 ET, incl. FOMC): still ahead
Well-known releases are anchored to their CANONICAL ET time (CPI=08:30,
FOMC=14:00, ...) rather than the feed timestamp, which sidesteps a timezone
ambiguity in Finnhub's calendar 'time' field.

Last updated: 2026-07-04
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass, field
from typing import Any
from zoneinfo import ZoneInfo

import requests

import config

_ET = ZoneInfo("America/New_York")

# Hand-authored magnitude tiers (0..1) by release type. Tune to your view of
# how much each print moves the tape, independent of sentiment direction.
MACRO_MAGNITUDE = {
    "FOMC_RATE_DECISION": 1.00,
    "FOMC_MINUTES":       0.70,
    "FED_CHAIR_SPEECH":   0.75,
    "CPI":                0.95,
    "CORE_CPI":           0.95,
    "PCE":                0.85,
    "PPI":                0.70,
    "NFP":                0.95,
    "JOBLESS_CLAIMS":     0.45,
    "JOLTS":              0.55,
    "RETAIL_SALES":       0.70,
    "GDP":                0.75,
    "ISM_MANUFACTURING":  0.60,
    "ISM_SERVICES":       0.60,
    "UMICH_SENTIMENT":    0.45,
}
DEFAULT_MACRO_MAGNITUDE = 0.40

# Canonical ET release time by type (hour, minute). Used as the display/
# bucketing anchor when available — more reliable than the feed timestamp.
TYPICAL_RELEASE_ET = {
    "CPI":                (8, 30),
    "CORE_CPI":           (8, 30),
    "PPI":                (8, 30),
    "NFP":                (8, 30),
    "JOBLESS_CLAIMS":     (8, 30),
    "RETAIL_SALES":       (8, 30),
    "GDP":                (8, 30),
    "PCE":                (8, 30),
    "JOLTS":              (10, 0),
    "ISM_MANUFACTURING":  (10, 0),
    "ISM_SERVICES":       (10, 0),
    "UMICH_SENTIMENT":    (10, 0),
    "FOMC_RATE_DECISION": (14, 0),
    "FOMC_MINUTES":       (14, 0),
    # FED_CHAIR_SPEECH intentionally omitted — time varies, use feed value.
}

# Report goes out 09:15 ET; anything at/after open that isn't pre-open is
# "still ahead". These labels are for the reader.
WINDOW_PRE_OPEN = "PRE_OPEN"
WINDOW_MID_MORNING = "MID_MORNING"   # ~10:00 ET
WINDOW_AFTERNOON = "AFTERNOON"       # ~14:00 ET (FOMC lives here)

_MATCHERS = [
    ("federal funds", "FOMC_RATE_DECISION"),
    ("fomc", "FOMC_RATE_DECISION"),
    ("interest rate decision", "FOMC_RATE_DECISION"),
    ("cpi", "CORE_CPI"),
    ("consumer price", "CPI"),
    ("pce", "PCE"),
    ("ppi", "PPI"),
    ("producer price", "PPI"),
    ("nonfarm", "NFP"),
    ("non-farm", "NFP"),
    ("payroll", "NFP"),
    ("initial jobless", "JOBLESS_CLAIMS"),
    ("jolts", "JOLTS"),
    ("retail sales", "RETAIL_SALES"),
    ("gdp", "GDP"),
    ("ism manufacturing", "ISM_MANUFACTURING"),
    ("ism services", "ISM_SERVICES"),
    ("michigan", "UMICH_SENTIMENT"),
]


@dataclass
class MacroEvent:
    event_type: str
    label: str
    release_et: dt.datetime          # tz-aware, America/New_York
    magnitude: float
    window: str
    actual: str | None = None
    forecast: str | None = None
    previous: str | None = None

    @property
    def release_utc(self) -> dt.datetime:
        return self.release_et.astimezone(dt.timezone.utc)

    @property
    def et_clock(self) -> str:
        return self.release_et.strftime("%-I:%M%p ET").lower()

    def surprise_note(self) -> str:
        if self.actual and self.forecast:
            return f"actual {self.actual} vs est {self.forecast}"
        if self.forecast:
            return f"est {self.forecast}"
        return "scheduled"


def _canonical(event_str: str) -> str | None:
    low = event_str.lower()
    for kw, canon in _MATCHERS:
        if kw in low:
            return canon
    return None


def _effective_et(canon: str, feed_str: str, day: dt.date) -> dt.datetime:
    """Prefer canonical ET anchor; fall back to parsing the feed timestamp."""
    if canon in TYPICAL_RELEASE_ET:
        h, m = TYPICAL_RELEASE_ET[canon]
        return dt.datetime.combine(day, dt.time(h, m), tzinfo=_ET)
    # fall back: parse feed value, treat as UTC, convert to ET
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%Y-%m-%d"):
        try:
            naive = dt.datetime.strptime(feed_str, fmt)
            return naive.replace(tzinfo=dt.timezone.utc).astimezone(_ET)
        except ValueError:
            continue
    return dt.datetime.combine(day, dt.time(9, 0), tzinfo=_ET)


def _window_for(rel_et: dt.datetime, report_et: dt.datetime | None) -> str:
    ref = report_et.timetz() if report_et else dt.time(9, 15, tzinfo=_ET)
    t = rel_et.timetz()
    if (t.hour, t.minute) <= (ref.hour, ref.minute):
        return WINDOW_PRE_OPEN
    if rel_et.hour < 12:
        return WINDOW_MID_MORNING
    return WINDOW_AFTERNOON


def fetch_macro(key: str, day: dt.date | None = None,
                report_et: dt.datetime | None = None) -> list[MacroEvent]:
    day = day or dt.datetime.now(_ET).date()
    if not key:
        print("[macro] no key -> calendar skipped (magnitude table still active)")
        return []
    try:
        r = requests.get(
            "https://finnhub.io/api/v1/calendar/economic",
            params={"from": day.isoformat(), "to": day.isoformat(), "token": key},
            timeout=config.HTTP_TIMEOUT,
        )
        r.raise_for_status()
        rows = (r.json() or {}).get("economicCalendar", []) or []
    except Exception as exc:
        print(f"[macro] calendar fetch error: {exc}")
        return []

    events: list[MacroEvent] = []
    for row in rows:
        if str(row.get("country", "")).upper() not in ("US", "USA", "UNITED STATES"):
            continue
        canon = _canonical(str(row.get("event", "")))
        if not canon:
            continue
        rel_et = _effective_et(canon, row.get("time") or row.get("date") or "", day)
        events.append(MacroEvent(
            event_type=canon,
            label=str(row.get("event", canon)),
            release_et=rel_et,
            magnitude=MACRO_MAGNITUDE.get(canon, DEFAULT_MACRO_MAGNITUDE),
            window=_window_for(rel_et, report_et),
            actual=_str_or_none(row.get("actual")),
            forecast=_str_or_none(row.get("estimate")),
            previous=_str_or_none(row.get("prev")),
        ))
    events.sort(key=lambda e: (e.release_et, -e.magnitude))
    print(f"[macro] {len(events)} US high-impact events for {day}")
    return events


def split_by_timing(events: list[MacroEvent]) -> tuple[list[MacroEvent], list[MacroEvent]]:
    """(already_out, still_ahead) — already_out = PRE_OPEN window."""
    out = [e for e in events if e.window == WINDOW_PRE_OPEN]
    ahead = [e for e in events if e.window != WINDOW_PRE_OPEN]
    return out, ahead


def is_fomc_day(events: list[MacroEvent]) -> bool:
    return any(e.event_type == "FOMC_RATE_DECISION" for e in events)


def _str_or_none(v: Any) -> str | None:
    if v in (None, "", "null"):
        return None
    return str(v)


# --------------------------------------------------------------------------
# Web-search-grounded fallback (used when the structured Finnhub call above
# comes back empty — e.g. its paid-plan gate on a free key). See config.py
# "6b. MACRO CALENDAR" for the cost/design rationale.
# --------------------------------------------------------------------------
_WEB_SYSTEM = (
    "You are a precise financial-calendar assistant. You search the web for "
    "the CURRENT day's US economic calendar and return ONLY structured JSON "
    "grounded in what you actually found. You clearly distinguish releases "
    "that have ALREADY printed today (with a real actual value from your "
    "search) from ones still scheduled later today. You never guess or "
    "invent a date, time, or number you did not find via search — if you "
    "cannot confirm an event, omit it rather than fabricate it."
)


def _web_user_prompt(day: dt.date, canonical_types: list[str]) -> str:
    return f"""Search the web for {day.isoformat()}'s US economic calendar —
"red folder" high-impact releases: FOMC statements/minutes, CPI, PPI, NFP,
jobless claims, JOLTS, retail sales, GDP, PCE, ISM manufacturing/services,
consumer sentiment, and any scheduled Fed chair speeches. Good sources:
Trading Economics, Forex Factory, Investing.com's economic calendar, or the
BLS/BEA/Fed's own release calendars.

For EACH confirmed high-impact US event scheduled today, return one object.
If it already printed today, include the actual and forecast values you
found. If it's still ahead today, set "actual" to null.

Canonical event_type values (use exactly one of these, or omit the event if
none fit): {', '.join(canonical_types)}

Return ONLY a JSON array (empty array "[]" if nothing high-impact today):
[
  {{
    "event_type": "<one canonical value>",
    "label": "<human label, e.g. 'Core CPI (MoM)'>",
    "release_time_et": "<HH:MM in 24-hour Eastern Time>",
    "actual": "<string or null>",
    "forecast": "<string or null>",
    "previous": "<string or null>"
  }}
]
JSON only. No prose, no markdown fences, no commentary."""


def _parse_et_clock(s: str, day: dt.date) -> dt.datetime:
    try:
        h, m = str(s).strip().split(":")
        return dt.datetime.combine(day, dt.time(int(h), int(m)), tzinfo=_ET)
    except (ValueError, AttributeError, TypeError):
        return dt.datetime.combine(day, dt.time(9, 0), tzinfo=_ET)


def fetch_macro_web(client, model: str, day: dt.date | None = None,
                    report_et: dt.datetime | None = None) -> list[MacroEvent]:
    """Fallback macro calendar via a web-search-grounded LLM call. Intended
    for when fetch_macro() returns [] because the structured Finnhub source
    is unavailable (paid-plan gate) or errored — not a replacement for it,
    a safety net behind it. Every field is sanitized/validated the same way
    triage.py and scope.py validate LLM output: unknown event types and
    malformed rows are dropped rather than trusted.
    """
    day = day or dt.datetime.now(_ET).date()
    canonical = list(MACRO_MAGNITUDE.keys())
    raw = client.web_search_json_call(
        model=model, system=_WEB_SYSTEM,
        user=_web_user_prompt(day, canonical),
        max_tokens=1500, max_uses=config.MACRO_WEB_MAX_SEARCHES)

    if not isinstance(raw, list):
        print(f"[macro] web-search fallback: no usable list returned")
        return []

    events: list[MacroEvent] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        et = item.get("event_type")
        if et not in MACRO_MAGNITUDE:
            continue  # unknown/hallucinated type -> drop rather than guess
        rel = _parse_et_clock(item.get("release_time_et", ""), day)
        events.append(MacroEvent(
            event_type=et,
            label=str(item.get("label", et))[:120],
            release_et=rel,
            magnitude=MACRO_MAGNITUDE.get(et, DEFAULT_MACRO_MAGNITUDE),
            window=_window_for(rel, report_et),
            actual=_str_or_none(item.get("actual")),
            forecast=_str_or_none(item.get("forecast")),
            previous=_str_or_none(item.get("previous")),
        ))
    events.sort(key=lambda e: (e.release_et, -e.magnitude))
    print(f"[macro] web-search fallback: {len(events)} events for {day}")
    return events
