# market_brief/data/fomc_cal.py — market_brief_v1.9.0
"""
FOMC MEETING DAYS, FROM THE BOARD'S OWN CALENDAR.

v1.0.0 — 2026-09-26 — the "decisions" half of the operator's request to FRED:
*"I need to know when FED red folder days are meeting to announce economic
figures and decisions."*

🔴 WHY THIS IS NOT FRED. FRED publishes a release called "FOMC Press Release"
(id 101) and it is NOT A MEETING NOTICE — it is a data feed that refreshes
daily. MEASURED, not assumed: over the 30-day window 2026-08-27..2026-09-25 it
fired on 30 of 30 dates. Keying on it put "FOMC statement 2:00pm" on every
weekday of the same week. The FOMC meets EIGHT TIMES A YEAR.
⚠️ A DAILY FALSE LANDMINE IS WORSE THAN A MISSING ONE. It is §17 every single
morning, and by the third day the reader has stopped seeing the section.

So the meeting dates come from federalreserve.gov's own calendar, which is
published roughly a year ahead and is the authority on its own schedule.

⚠️ THE DECISION IS ON THE SECOND DAY. Meetings are two days ("27-28") and the
statement lands at 14:00 ET on the SECOND. A brief that flags day one as the
decision day is wrong in the direction that matters — it tells the reader the
risk is today when it is tomorrow.

⚠️ THE ASTERISK IS INFORMATION, NOT DECORATION. A starred meeting carries the
Summary of Economic Projections and a press conference, which is a materially
bigger event than a statement alone. It is carried through as `sep`.

📊 PARSED AND CHECKED: 8 meetings for 2026 and 8 for 2027, verified against
the page by eye. A first parser returned FOUR because its month and date
regexes were run separately and misaligned — and four-of-eight is worse than
zero, because the four look complete.

🔴 THE PARSER IS FRAGILE ON HISTORY AND THAT IS STATED RATHER THAN HIDDEN.
Across the whole page it yields 8/8/6/8/9/8/8 for 2021..2027:
  · 2023 comes back SIX — it drops the two MONTH-SPANNING meetings
    (Jan/Feb and Oct/Nov), whose rows this regex does not match.
  · 2025 comes back NINE — one spurious row, 2025-08-22, which is not an
    FOMC meeting.
Neither affects the brief: 2026 and 2027 contain no month-spanning meetings,
so both forward years are complete and correct. But a parser that is wrong in
BOTH directions on history could be wrong on a future year the day the Board
schedules a Jan/Feb meeting again.
⚠️ SO ONLY THE CURRENT YEAR ONWARD IS SERVED (`meetings()` filters), and the
gate ASSERTS 8 PER YEAR ON EXACTLY THOSE. A year that comes back with any
other count is a REFUSAL, not a short list — because a short list of meeting
days looks exactly like a complete one to a reader.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import re
import html as _html
from zoneinfo import ZoneInfo

import requests

URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
ET = ZoneInfo("America/New_York")
DECISION_ET = (14, 0)
CACHE = os.environ.get("MB_FOMC_CACHE",
                       os.path.expanduser("~/market-brief/data/fomc_cache.json"))
CACHE_MAX_AGE_D = 30

_MONTHS = {m: i + 1 for i, m in enumerate(
    ["january", "february", "march", "april", "may", "june", "july",
     "august", "september", "october", "november", "december"])}


def parse(page: str) -> list[dict]:
    """[{date: ISO of the DECISION day, sep: bool}], every year on the page."""
    out: list[dict] = []
    for ym in re.finditer(r'(20\d\d) FOMC Meetings', page):
        yr = int(ym.group(1))
        nxt = page.find('FOMC Meetings', ym.end())
        blk = page[ym.end(): nxt if nxt > 0 else len(page)]
        pairs = re.findall(
            r'fomc-meeting__month[^>]*>\s*<strong>([^<]+)</strong>'
            r'.*?fomc-meeting__date[^>]*>\s*([^<]+?)\s*<', blk, re.S)
        for mo_raw, dy_raw in pairs:
            mo = _html.unescape(mo_raw).strip().lower()
            dy = _html.unescape(dy_raw).strip()
            sep = "*" in dy
            nums = re.findall(r"\d+", dy)
            if not nums:
                continue
            # A meeting spanning two months renders as "April/May"; the
            # DECISION day belongs to the month the second date falls in.
            parts = [p.strip() for p in mo.split("/")]
            month_name = parts[-1] if len(parts) > 1 and len(nums) > 1 else parts[0]
            m = _MONTHS.get(month_name)
            if not m:
                continue
            day = int(nums[-1])            # second day = decision day
            try:
                out.append({"date": dt.date(yr, m, day).isoformat(), "sep": sep})
            except ValueError:
                continue
    return out


def _cached() -> list[dict] | None:
    try:
        st = os.stat(CACHE)
        if (dt.datetime.now().timestamp() - st.st_mtime) / 86400 > CACHE_MAX_AGE_D:
            return None
        return json.load(open(CACHE)).get("meetings")
    except Exception:                                             # noqa: BLE001
        return None


def forward_years_ok(ms: list[dict], this_year: int | None = None):
    """(ok, detail). Every year from the current one on must hold exactly 8."""
    y0 = this_year or dt.date.today().year
    per: dict[int, int] = {}
    for m in ms:
        y = int(m["date"][:4])
        if y >= y0:
            per[y] = per.get(y, 0) + 1
    bad = {y: n for y, n in per.items() if n != 8}
    return (not bad and bool(per)), (bad or per)


def meetings(force: bool = False, all_years: bool = False) -> list[dict]:
    """Cached for 30 days — the Board publishes a year ahead, so this is not a
    figure that moves, and a brief must not depend on a live fetch at 09:00.

    Returns the CURRENT YEAR ONWARD unless all_years. See the header: the
    parser is measurably wrong on two historical years and serving them would
    be publishing numbers known to be incomplete."""
    def _cut(ms):
        if all_years:
            return ms
        y0 = dt.date.today().year
        return [m for m in ms if int(m["date"][:4]) >= y0]

    if not force:
        c = _cached()
        if c:
            return _cut(c)
    r = requests.get(URL, timeout=30,
                     headers={"User-Agent": "vertigo-market-brief/1.0"})
    r.raise_for_status()
    got = parse(r.text)
    if got:
        try:
            os.makedirs(os.path.dirname(CACHE), exist_ok=True)
            json.dump({"fetched": dt.datetime.now(dt.timezone.utc).isoformat(),
                       "meetings": got}, open(CACHE, "w"), indent=2)
        except Exception:                                         # noqa: BLE001
            pass
    return _cut(got)


def decision_on(day: dt.date, force: bool = False):
    """(is_decision_day, sep_flag). Never raises — a calendar we could not
    reach must not take the whole brief down with it."""
    try:
        for m in meetings(force=force):
            if m["date"] == day.isoformat():
                return True, bool(m.get("sep"))
    except Exception:                                             # noqa: BLE001
        return False, False
    return False, False
