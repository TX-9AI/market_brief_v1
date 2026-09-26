#!/usr/bin/env python3
# market_brief/tests/check_macro_fred.py — market_brief_v1.8.0
"""
THE MACRO CALENDAR COMES FROM THE FED, AND THE CLOCK IS A CONVENTION.

v1.0.0 — 2026-09-26 — written with data/macro_fred.py.

OPERATOR, 2026-09-26, on losing the macro section: *"That is vital
information."* It is, which is why it comes back on a source that publishes
for programs rather than one we would be taking from.

WHY FRED AND NOT THE OTHERS, MEASURED RATHER THAN PREFERRED:
  · Finnhub's economic calendar — PAYWALLED, live 403 on our key (config §6b).
  · baha — `/economic-calendar` 302s to a login AND the whole site sits behind
    a Cloudflare managed challenge; robots.txt itself is unreadable.
  · Yahoo Finance — robots.txt lists `anthropic-ai`, `ClaudeBot` and
    `Claude-Web` under `Disallow: /`.
  · FRED — a published developer API on api.stlouisfed.org, free key.

🔴 M3 IS THE CHECK THAT MATTERS AND IT IS ABOUT HONESTY, NOT CORRECTNESS.
FRED RETURNS A DATE. IT DOES NOT RETURN A TIME. The clock we print beside each
release is OUR CONVENTION — BLS prints at 08:30 ET, Michigan at 10:00 — and a
convention rendered in the same typeface as a measurement is how a reader ends
up trusting a number nobody measured. The section must SAY the times are
conventional. If M3 ever goes green by deleting the disclaimer instead of
keeping it, we have started asserting a schedule we do not source.

⚠️ M2 IS THE ONE THAT WOULD HAVE SHIPPED WRONG. FRED's
`include_release_dates_with_no_data` DEFAULTS TO FALSE, which excludes any
release that has no data yet — i.e. EVERY RELEASE STILL AHEAD THIS MORNING.
The obvious call returns a calendar that can only ever show you what already
happened, which for a 09:00 pre-market brief is precisely backwards and would
have looked like a quiet morning rather than a broken query.

⚠️ M5 — NO KEY IS NOT AN EMPTY CALENDAR. The key is not provisioned yet, so
the common case at the time of writing is the absent one, and it must NAME
itself. Same §0.5 rule the rest of this brief follows.

BORN RED, verified 2026-09-26 against the pre-change repo:
  M1-M5 -> "data.macro_fred is absent"

MUTATIONS — each reddens exactly one check:
  * drop include_release_dates_with_no_data (or set it false)  -> M2 only
  * remove the "times are conventional" disclaimer             -> M3 only
  * let an unknown release through with a guessed clock        -> M4 only
  * return [] instead of raising/ flagging on a missing key    -> M5 only

Run:  cd ~/market-brief && python3 tests/check_macro_fred.py
"""
from __future__ import annotations

import datetime as dt
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                                                    # noqa: E402

_fails: list[str] = []


def ck(tag, ok, msg=""):
    print(f"  {'PASS' if ok else 'FAIL'}  {tag}  {msg}")
    if not ok:
        _fails.append(tag)


# A FRED-shaped payload. Two known releases and one obscure one that must NOT
# be invented a time for.
_PAYLOAD = {"release_dates": [
    {"release_id": 10, "release_name": "Consumer Price Index",
     "date": "2026-09-28"},
    {"release_id": 91, "release_name": "Surveys of Consumers",
     "date": "2026-09-28"},
    {"release_id": 999, "release_name": "Kansas City Fed Widget Index",
     "date": "2026-09-28"},
]}


class _Resp:
    def __init__(self, payload, code=200):
        self._p, self.status_code = payload, code
        self.text = json.dumps(payload)

    def json(self):
        return self._p

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def main() -> int:
    try:
        from data import macro_fred
    except Exception as exc:                                      # noqa: BLE001
        for t in ("M1", "M2", "M3", "M4", "M5"):
            ck(t, False, f"data.macro_fred is absent ({type(exc).__name__})")
        print(f"\nRED — {len(_fails)} check(s) failed: {' '.join(_fails)}")
        return 1

    day = dt.date(2026, 9, 28)
    seen = {}

    def _fake_get(url, params=None, timeout=None, **kw):
        seen["url"], seen["params"] = url, dict(params or {})
        return _Resp(_PAYLOAD)

    real = getattr(macro_fred, "requests", None)

    class _Req:
        @staticmethod
        def get(url, params=None, timeout=None, **kw):
            return _fake_get(url, params, timeout, **kw)

    macro_fred.requests = _Req
    try:
        events = macro_fred.fetch_macro_fred("a" * 32, day)
    except Exception as exc:                                      # noqa: BLE001
        events, seen["err"] = [], f"{type(exc).__name__}: {exc}"
    finally:
        if real is not None:
            macro_fred.requests = real

    # ── M1 — IT HITS THE API HOST AND RETURNS MacroEvent-SHAPED ROWS ────
    from data.macro_cal import MacroEvent
    ok_shape = events and all(isinstance(e, MacroEvent) for e in events)
    ck("M1", bool(ok_shape) and "api.stlouisfed.org" in seen.get("url", ""),
       f"{len(events)} event(s) from {seen.get('url','<no call>')}"
       + (f" · {seen['err']}" if "err" in seen else ""))

    # ── M2 — UPCOMING RELEASES ARE ASKED FOR ────────────────────────────
    p = seen.get("params", {})
    flag = str(p.get("include_release_dates_with_no_data", "")).lower()
    ck("M2", flag == "true",
       f"include_release_dates_with_no_data={flag or '<absent>'} — must be "
       f"true, or the morning's STILL-AHEAD releases are all filtered out and "
       f"a broken query looks like a quiet calendar")

    # ── M3 — THE CLOCK IS LABELLED AS A CONVENTION ──────────────────────
    note = getattr(macro_fred, "CLOCK_DISCLAIMER", "")
    ck("M3", bool(note) and "convention" in note.lower(),
       f"CLOCK_DISCLAIMER={note!r} — FRED returns a DATE and no TIME; the "
       f"clock is ours and must say so")

    # ── M4 — AN UNKNOWN RELEASE IS DROPPED, NEVER GIVEN A GUESSED TIME ──
    names = {getattr(e, "label", "") for e in events}
    ck("M4", not any("Widget" in n for n in names) and len(events) == 2,
       f"kept {sorted(names)} — a release with no known publication time must "
       f"be dropped rather than assigned one")

    # ── M5 — A MISSING KEY NAMES ITSELF ─────────────────────────────────
    raised = ""
    try:
        macro_fred.fetch_macro_fred("", day)
    except Exception as exc:                                      # noqa: BLE001
        raised = f"{type(exc).__name__}: {exc}"
    ck("M5", "key" in raised.lower(),
       f"no-key call raised {raised or '<nothing — returned silently>'}")

    if _fails:
        print(f"\nRED — {len(_fails)} check(s) failed: {' '.join(_fails)}")
        return 1
    print("\nGREEN — the calendar is the Fed's, and the clock admits it is ours")
    return 0


if __name__ == "__main__":
    sys.exit(main())
