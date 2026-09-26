# market_brief/data/macro_fred.py — market_brief_v1.9.0
"""
THE MACRO CALENDAR, FROM THE FED'S OWN RELEASE SCHEDULE.

v1.1.0 — 2026-09-26 — KEYED ON RELEASE ID, NOT ON NAME SUBSTRINGS, and FOMC
         meeting days come from the Board's calendar rather than from FRED.
         Operator: *"Can't you poll the available parameters using the API
         call?"* — yes, and it is the right way; `/fred/releases` returns the
         whole 332-release catalogue, so every id here was RESOLVED FROM THE
         SOURCE. See the RELEASES note for the two failures the name matching
         produced, both measured against the operator's own screenshot of the
         2026-09-25 calendar.
v1.0.0 — 2026-09-26 — replaces the web-search model call removed at v1.7.0.

Operator, 2026-09-26, on the section going dark: *"That is vital
information."*

WHY THIS SOURCE, MEASURED RATHER THAN PREFERRED:
  · Finnhub's economic calendar is PAYWALLED — a live 403 on our free key,
    recorded in config §6b. It is why the section ever needed a model.
  · baha: `/economic-calendar` 302s to a login, and the whole site is behind a
    Cloudflare managed challenge — `robots.txt` itself will not load. Gated
    twice. Their data, their terms; the clean route there is buying a feed.
  · Yahoo Finance: robots.txt names `anthropic-ai`, `ClaudeBot` and
    `Claude-Web` in a group whose directive is `Disallow: /`.
  · FRED: a published developer API, free key, built to be called by programs.

🔴 FRED RETURNS A DATE. IT DOES NOT RETURN A TIME — AND THAT IS THE WHOLE
DESIGN CONSTRAINT OF THIS FILE. The clock beside each release is OUR
CONVENTION: BLS publishes at 08:30 ET, the Michigan survey at 10:00, the FOMC
statement at 14:00. Those are stable, publicly documented habits, and they are
still conventions rather than a field we were handed. The brief says so out
loud (`CLOCK_DISCLAIMER`), because a convention rendered in the same typeface
as a measurement is how a reader ends up trusting a number nobody measured —
which is C.46's whole complaint, one section over.

🔴 AND A RELEASE WE HAVE NO TIME FOR IS DROPPED, NOT GUESSED. `SCHEDULE` is
the whitelist AND the clock in one structure, so there is no path that prints
a release without a sourced habit behind it. FRED lists hundreds of releases,
most of them regional and none of them market-moving at 09:00; inventing
"08:30" for the Kansas City Fed's widget index would be fabricating the one
field the reader actually acts on.

⚠️ `include_release_dates_with_no_data=true` IS LOAD-BEARING AND THE DEFAULT
IS WRONG FOR US. It defaults to FALSE, which excludes any release that has no
data yet — that is EVERY RELEASE STILL AHEAD at 09:00. The obvious call
returns a calendar that can only show what already happened, and a pre-market
brief built on it would have rendered a busy morning as a quiet one: a broken
query wearing the costume of good news.
"""

from __future__ import annotations

import datetime as dt
from zoneinfo import ZoneInfo

import requests

import config
from data.macro_cal import MacroEvent

API = "https://api.stlouisfed.org/fred/releases/dates"
ET = ZoneInfo("America/New_York")
HTTP_TIMEOUT = getattr(config, "HTTP_TIMEOUT", 20)

CLOCK_DISCLAIMER = (
    "Release times are the publishing agency's standing convention, not a "
    "field FRED returns; FRED supplies the date only."
)

# name-substring -> (display label, ET publication habit, magnitude 1-3)
# Matching is on the NAME rather than the numeric release id on purpose: ids
# are an implementation detail of FRED's catalogue, names are what the agency
# calls the release and what a reader recognises at 09:00.
# ── THE WHITELIST IS KEYED ON FRED'S RELEASE ID, NOT ITS NAME ──────────────
# Operator, 2026-09-26: *"Can't you poll the available parameters using the API
# call?"* — yes, and it is the right way. `/fred/releases` returns the whole
# catalogue (332 releases), so the ids below were RESOLVED FROM THE SOURCE
# rather than guessed, and the name is now only a display label.
#
# 🔴 THE FIRST CUT MATCHED ON NAME SUBSTRINGS AND FAILED IN BOTH DIRECTIONS,
# MEASURED AGAINST THE OPERATOR'S OWN SCREENSHOT OF 2026-09-25:
#   · MISSED Durable Goods entirely. FRED does not call it that. It files the
#     release as "Manufacturer's Shipments, Inventories, and Orders (M3)
#     Survey" (id 95), so the obvious needle matched NOTHING while the release
#     sat in the response the whole time — a silent miss that reads as a quiet
#     calendar.
#   · INVENTED Jobless Claims on a Friday, because "State Unemployment
#     Insurance Weekly Claims Report" (id 469) is a DIFFERENT, near-daily
#     release from the national "Unemployment Insurance Weekly Claims Report"
#     (id 180, Thursdays) and one substring caught both.
# An id cannot do either. A name written from what a release is CALLED IN THE
# WORLD rather than what THE SOURCE calls it fails silently, every time.
#
# 📊 MEMBERSHIP IS MEASURED, NOT ASSUMED. Over 2026-08-27..2026-09-25 (30
# dates, 820 rows, 160 distinct releases) the catalogue splits cleanly: ~28
# releases fire on almost every date and are DATA FEEDS, not calendar events
# (Coinbase Cryptocurrencies, SOFR, Nasdaq Daily, "FOMC Press Release"), while
# the real economic releases fire once or twice a month. Everything below came
# from the periodic side of that measurement.
#
# ⚠️ THE CLOCK IS STILL A CONVENTION — see CLOCK_DISCLAIMER. FRED returns a
# DATE and never a TIME. These are the publishing agencies' standing habits.
RELEASES: dict[int, tuple[str, str, int]] = {
    # id: (display label, ET publication habit, magnitude 1-3)
     10: ("CPI",                     "08:30", 3),
     50: ("Employment Situation",    "08:30", 3),
     53: ("GDP",                     "08:30", 3),
     54: ("PCE / Personal Income",   "08:30", 3),
      9: ("Retail Sales",            "08:30", 3),
     46: ("PPI",                     "08:30", 2),
     95: ("Durable Goods Orders",    "08:30", 2),   # the M3 survey
    180: ("Jobless Claims",          "08:30", 2),   # national, Thursdays
    194: ("ADP Employment",          "08:15", 2),
    192: ("JOLTS",                   "10:00", 2),
     91: ("Michigan Sentiment",      "10:00", 2),
     51: ("Trade Balance",           "08:30", 1),
    188: ("Import/Export Prices",    "08:30", 1),
     47: ("Productivity & Costs",    "08:30", 1),
     27: ("Housing Starts",          "08:30", 1),
     97: ("New Home Sales",          "10:00", 1),
    229: ("Construction Spending",   "10:00", 1),
    321: ("Empire State Mfg",        "08:30", 1),
    351: ("Philly Fed Mfg",          "08:30", 1),
     13: ("Industrial Production",   "09:15", 1),
     14: ("Consumer Credit",         "15:00", 1),
    326: ("FOMC Projections (SEP)",  "14:00", 3),
}

# 🔴 id 101 "FOMC Press Release" IS DELIBERATELY ABSENT. Measured: it fired on
# 30 of 30 dates in the window above. It is a feed that refreshes daily, not a
# meeting notice, and keying on it put an FOMC statement on every weekday of
# the same week. Meeting days come from data/fomc_cal.py, the Board's own
# published calendar. See that module's header.
FEED_NOT_EVENT = {101}


def _match(release_id) -> tuple[str, str, int] | None:
    try:
        return RELEASES.get(int(release_id))
    except (TypeError, ValueError):
        return None


def fetch_macro_fred(api_key: str, day: dt.date) -> list[MacroEvent]:
    """Releases scheduled for `day`, as MacroEvent. Raises on a missing key.

    ⚠️ RAISES rather than returning [] when the key is absent. An empty list
    is indistinguishable from a quiet calendar, and the caller renders those
    two facts differently on purpose (§0.5). The key is the one input this
    function cannot substitute for, so it says so instead of shrugging.
    """
    if not api_key:
        raise ValueError(
            "FRED_API_KEY is not set — refusing to report an empty calendar as "
            "a quiet one. Free key: fred.stlouisfed.org/docs/api/api_key.html")

    iso = day.isoformat()
    r = requests.get(API, params={
        "api_key": api_key,
        "file_type": "json",
        "realtime_start": iso,
        "realtime_end": iso,
        # ⚠️ see the module header — the default (false) hides everything that
        # has not been published yet, i.e. the entire morning.
        "include_release_dates_with_no_data": "true",
        "limit": 1000,
        "sort_order": "asc",
    }, timeout=HTTP_TIMEOUT)
    r.raise_for_status()
    rows = (r.json() or {}).get("release_dates") or []

    out: list[MacroEvent] = []
    for row in rows:
        if row.get("date") != iso:
            continue
        hit = _match(row.get("release_id"))
        if not hit:
            continue                      # no sourced time -> not printed
        label, clock, mag = hit
        hh, mm = (int(x) for x in clock.split(":"))
        if any(e.label == label for e in out):
            continue                      # one line per release per day
        out.append(MacroEvent(
            event_type=str(row.get("release_id", "")),
            label=label,
            release_et=dt.datetime(day.year, day.month, day.day, hh, mm,
                                   tzinfo=ET),
            magnitude=mag,
            window="pre" if (hh, mm) < (9, 30) else "post",
        ))
    # ── FOMC DECISION DAYS, FROM THE BOARD'S OWN CALENDAR ───────────────
    # Not from FRED: its "FOMC Press Release" (id 101) fires DAILY and cannot
    # identify a meeting. See data/fomc_cal.py. This never raises — a calendar
    # we could not reach must not take the macro section down with it.
    try:
        from data import fomc_cal
        is_day, sep = fomc_cal.decision_on(day)
        if is_day:
            # ⚠️ DO NOT PRINT THE SAME EVENT TWICE. FRED's "Summary of
            # Economic Projections" (id 326) lands on exactly the starred
            # meetings, so on a SEP day the reader would have been told at
            # 2:00pm ET twice in two wordings. The Board-sourced line is
            # richer (it names the press conference), so the FRED row yields.
            # Same shape as the r428 gate that reported one finding twice:
            # a double-report makes a section's own count untrustworthy.
            out = [e for e in out if e.event_type != "326"]
            out.append(MacroEvent(
                event_type="fomc",
                label=("FOMC decision + projections & press conference" if sep
                       else "FOMC decision"),
                release_et=dt.datetime(day.year, day.month, day.day, 14, 0,
                                       tzinfo=ET),
                magnitude=3, window="post"))
    except Exception:                                             # noqa: BLE001
        pass

    out.sort(key=lambda e: e.release_et)
    return out
