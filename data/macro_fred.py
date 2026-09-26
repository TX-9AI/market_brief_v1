# market_brief/data/macro_fred.py — market_brief_v1.8.0
"""
THE MACRO CALENDAR, FROM THE FED'S OWN RELEASE SCHEDULE.

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
SCHEDULE: list[tuple[str, str, str, int]] = [
    ("consumer price index",                    "CPI",                       "08:30", 3),
    ("employment situation",                    "Employment Situation",      "08:30", 3),
    ("gross domestic product",                  "GDP",                       "08:30", 3),
    ("personal income and outlays",             "PCE / Personal Income",     "08:30", 3),
    ("producer price index",                    "PPI",                       "08:30", 2),
    ("advance monthly sales for retail",        "Retail Sales",              "08:30", 3),
    ("advance report on durable goods",         "Durable Goods Orders",      "08:30", 2),
    ("unemployment insurance weekly claims",    "Jobless Claims",            "08:30", 2),
    ("new residential construction",            "Housing Starts",            "08:30", 1),
    ("job openings and labor turnover",         "JOLTS",                     "10:00", 2),
    ("industrial production",                   "Industrial Production",     "09:15", 1),
    ("surveys of consumers",                    "Michigan Sentiment",        "10:00", 2),
    ("federal open market committee",           "FOMC statement",            "14:00", 3),
    ("fomc",                                    "FOMC statement",            "14:00", 3),
]


def _match(release_name: str):
    low = (release_name or "").lower()
    for needle, label, clock, mag in SCHEDULE:
        if needle in low:
            return label, clock, mag
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
        hit = _match(row.get("release_name", ""))
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
    out.sort(key=lambda e: e.release_et)
    return out
