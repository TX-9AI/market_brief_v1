#!/usr/bin/env python3
# market_brief/tests/check_information_brief.py — market_brief_v1.7.0
"""
THE BRIEF IS INFORMATION. This checks that, by execution.

v1.0.1 — 2026-09-26 — I4 REWRITTEN PER SECTION after mutation M4 reddened
         nothing. The first cut compared whole briefs, so one conflating
         section hid behind three correct ones. Recorded rather than quietly
         fixed: a gate that passes its own mutation is not a gate.
v1.0.0 — 2026-09-26 — written for the information-only collapse.

OPERATOR, 2026-09-25: *"I want to de-emphasize the market brief part of the
morning rollout. It should come out at the same time every day and cover the
symbols that we trade, including the two new ones. And have that be
Information only. No LLM's. Or discretionary decisions—just a brief and that's
it. The reason for this is the market brief never actually correlated with the
days Trading — it was Information, but there was no edge to be gained and no
morning bias ended up correlating."*

🔑 THIS FINISHES A RULING THAT WAS ONLY HALF-APPLIED. otv4 C.46 (r382,
2026-09-14) already ruled that *"no score is shown to a trader, ranked into a
look-here-first list or read by a bot until it is validated against what it
claims to represent."* The BOT half was closed — `risk/setup_scorer.py` was
deleted at OTV4 r152 and `config.BRIEF_CONVICTION_WEIGHT` has had zero readers
ever since. ⚠️ THE READER HALF WAS NEVER CLOSED: the brief has gone on printing
*"BOTTOM LINE — LOOK HERE FIRST"* — a ranked, LLM-scored, signed-direction list
— to the operator's phone every weekday morning for the eleven days since. The
ruling names the trader FIRST and the bot second; we applied it second-first.

⚠️ IT IS A PLAIN SCRIPT WITH AN EXIT CODE, NOT A PYTEST FILE. A verification
that goes red on ENVIRONMENT rather than CONTENT teaches an operator to ignore
reds. Same rule as tests/check_panel.py, which this file sits beside.

⚠️ EVERY CHECK EXECUTES THE CODE IT IS ABOUT. I1 POISONS `LLMClient` so that
constructing one is a TypeError, then runs the whole brief: a source-text grep
for "LLMClient" would pass against a file that still calls it through an alias,
and would fail against this file's own docstring — which is the checker
self-match that has now bitten this fleet five times (r417 §20, r420 P2, r423's
creep predicate, r426 P5, r428 G1).

🔑 I4 IS THE ONE THAT IS NOT ABOUT THE LLM. The v1.1.1 builder printed
"• None scheduled / calendar unavailable." for the macro section — ONE STRING
FOR TWO FACTS. A quiet calendar and a calendar that did not answer are
different mornings, and conflating them is the plausible-silence class this
fleet keeps paying for (otv4 GEX.1, SHD.4, OPS.6). An information-only brief
that cannot tell you whether it knows nothing or was told nothing is not
information.

BORN RED, verified 2026-09-26 against the pre-change repo:
  I1 -> "report.information is absent"        (module does not exist)
  I2 -> "report.information is absent"
  I3 -> "main.run_information_brief is absent"
  I4 -> "report.information is absent"
  I5 -> "main.run_information_brief is absent"
⚠️ ALL FIVE FAIL THROUGH ONE MODULE-ABSENT GUARD, so the born-red is HONEST
BUT WEAK ON ITS OWN — it proves the code is new, not that each check bites.
The per-check evidence is the mutation list below. Same caveat, stated the
same way, as otv4 OPS.47/F5 and OPS.50/R1-R8.

MUTATIONS — each reddens exactly one check (run after the change lands):
  * let the brief build an LLMClient again                       -> I1 only
  * re-add a score/arrow/rank to any rendered line               -> I2 only
  * poll a symbol outside config.UNIVERSE                        -> I3 only
  * collapse "none scheduled" and "unavailable" to one string    -> I4 only
  * emit `scores` or `move_ranked` into report.json              -> I5 only

Run:  cd ~/market-brief && python3 tests/check_information_brief.py
      (exit 0 == green)
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sys
import types

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                                                    # noqa: E402

_fails: list[str] = []


def ck(tag: str, ok: bool, msg: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {tag}  {msg}")
    if not ok:
        _fails.append(tag)


# ── fixtures ────────────────────────────────────────────────────────────────
ET = "America/New_York"


def _dt_et(h=9, m=0):
    from zoneinfo import ZoneInfo
    return dt.datetime(2026, 9, 28, h, m, tzinfo=ZoneInfo(ET))


class _Macro:
    def __init__(self, label, et_clock, magnitude=3, pre_open=True):
        self.label, self.et_clock, self.magnitude = label, et_clock, magnitude
        self.pre_open = pre_open
        self.actual = self.consensus = None


class _Earn:
    def __init__(self, symbol, date, session="amc"):
        self.symbol, self.date, self.session = symbol, date, session
        self.session_label = session.upper()


class _Head:
    def __init__(self, ticker, title, source):
        self.ticker, self.title, self.source = ticker, title, source


def _availability(**kw):
    """{source: True answered / False did not answer}."""
    base = {"macro": True, "earnings": True, "news": True, "prices": True}
    base.update(kw)
    return base


# ── the checks ──────────────────────────────────────────────────────────────
def main() -> int:
    try:
        from report import information
    except Exception as exc:                                      # noqa: BLE001
        information = None
        _abs_info = f"report.information is absent ({type(exc).__name__})"
    else:
        _abs_info = ""

    try:
        import main as brief_main
        runner = getattr(brief_main, "run_information_brief", None)
    except Exception as exc:                                      # noqa: BLE001
        brief_main, runner = None, None
        _abs_run = f"main did not import ({type(exc).__name__}: {exc})"
    else:
        _abs_run = "" if runner else "main.run_information_brief is absent"

    # ── I1 — THE BRIEF PATH NEVER CONSTRUCTS AN LLM CLIENT ──────────────
    # Poisoned by EXECUTION, not by grep: any construction raises.
    if not runner:
        ck("I1", False, _abs_run or _abs_info)
    else:
        import classify.llm_client as _llm
        _real = _llm.LLMClient

        class _Poison:
            def __init__(self, *a, **k):
                raise AssertionError("the information brief built an LLMClient")

        _llm.LLMClient = _Poison
        if brief_main is not None:
            setattr(brief_main, "LLMClient", _Poison)
        try:
            rc, err = _drive(brief_main, runner)
            ck("I1", rc == 0 and not err,
               f"ran the whole brief with LLMClient poisoned -> rc={rc}"
               + (f" · {err}" if err else " · no LLM constructed"))
        finally:
            _llm.LLMClient = _real
            if brief_main is not None:
                setattr(brief_main, "LLMClient", _real)

    # ── I2 — NOTHING RANKED, SCORED, OR POINTED ─────────────────────────
    if information is None:
        ck("I2", False, _abs_info)
    else:
        text, _ = information.build_information_brief(
            macro_events=[_Macro("CPI", "08:30")],
            earnings_events=[_Earn("AAL", dt.date(2026, 10, 1))],
            headlines=[_Head("NVDA", "Nvidia ships a thing", "finnhub")],
            prices={"NVDA": 196.4},
            report_dt_et=_dt_et(),
            availability=_availability(),
        )
        banned = ["LOOK HERE FIRST", "BOTTOM LINE", "🟢▲", "🔴▼", "⚪️•",
                  "BULLISH", "BEARISH", "conviction", "composite",
                  "SUPPORTING DETAIL", "rank", "score"]
        hit = [b for b in banned if b.lower() in text.lower()]
        ck("I2", not hit,
           f"rendered brief carries no ranking/scoring vocabulary"
           if not hit else f"brief still prints: {hit}")

    # ── I3 — THE SYMBOLS ARE THE ONES WE TRADE ──────────────────────────
    uni = list(getattr(config, "UNIVERSE", []))
    want = {"AAL", "SOFI"}
    ck("I3", len(uni) == 17 and want <= set(uni),
       f"UNIVERSE has {len(uni)} names; AAL/SOFI present: "
       f"{sorted(want & set(uni)) or 'neither'} (want 17 incl. both)")

    # ── I4 — AN ABSENT SOURCE IS NAMED, PER SECTION ─────────────────────
    # ⚠️ THIS CHECK TOOK THREE CUTS AND THE FIRST TWO WERE THE BUG THEY EXIST
    # TO CATCH. Recorded rather than quietly fixed (§0.1), because a gate that
    # survives its own mutation is decoration:
    #   cut 1 — compared WHOLE briefs. Collapsing one section hid behind the
    #           three still-correct ones. M4 reddened NOTHING.
    #   cut 2 — compared per section but asserted only that the dark render
    #           contains "UNAVAILABLE". v1.1.1's offending string is literally
    #           "None scheduled / calendar unavailable." — IT CONTAINS THE
    #           WORD. The check passed on the exact text it was written about.
    #   cut 3 — the real property: a section rendered EMPTY must not hint at
    #           unavailability, and a section rendered UNAVAILABLE must not
    #           ALSO claim emptiness. Conflation is a line asserting both.
    _HEADER = {"macro": "*MACRO TODAY*", "earnings": "*EARNINGS THIS WEEK*",
               "news": "*HEADLINES BY SYMBOL*", "prices": "*LAST PRICE*"}
    _EMPTY_CLAIMS = ("none scheduled", "nothing on the calendar", "none among",
                     "no headlines", "no prices returned", "none.")

    def _section(text: str, header: str) -> str:
        keep, on = [], False
        for ln in text.split("\n"):
            if ln.startswith(header):
                on = True
                continue
            if on and ln.startswith("*"):
                break
            if on:
                keep.append(ln)
        return "\n".join(keep).strip()

    if information is None:
        ck("I4", False, _abs_info)
    else:
        quiet, _ = information.build_information_brief(
            macro_events=[], earnings_events=[], headlines=[], prices={},
            report_dt_et=_dt_et(), availability=_availability())
        bad = []
        for src, hdr in _HEADER.items():
            dark, _ = information.build_information_brief(
                macro_events=[], earnings_events=[], headlines=[], prices={},
                report_dt_et=_dt_et(),
                availability=_availability(**{src: False}),
                reasons={src: "gate probe"})
            s_empty, s_dark = _section(quiet, hdr), _section(dark, hdr)
            if not s_dark:
                bad.append(f"{src}: no section rendered")
            elif s_empty == s_dark:
                bad.append(f"{src}: EMPTY and UNAVAILABLE are the same text")
            elif "unavailab" in s_empty.lower():
                bad.append(f"{src}: an EMPTY section hints unavailability")
            else:
                claim = [c for c in _EMPTY_CLAIMS if c in s_dark.lower()]
                if claim:
                    bad.append(f"{src}: an UNAVAILABLE section also claims "
                               f"emptiness {claim}")
        ck("I4", not bad,
           "empty and unavailable are distinct in every section, one source "
           "at a time" if not bad else "; ".join(bad))

    # ── I5 — THE JSON CARRIES NO SIGNAL PAYLOAD ─────────────────────────
    if not runner:
        ck("I5", False, _abs_run or _abs_info)
    else:
        rc, err, payload = _drive(brief_main, runner, want_json=True)
        if payload is None:
            ck("I5", False, f"no report.json was produced ({err or 'rc=%s' % rc})")
        else:
            bad = [k for k in ("scores", "move_ranked", "tickers", "landmines")
                   if k in payload]
            ck("I5", not bad,
               "report.json carries calendar + headlines only"
               if not bad else f"report.json still emits signal fields: {bad}")

    if _fails:
        print(f"\nRED — {len(_fails)} check(s) failed: {' '.join(_fails)}")
        return 1
    print("\nGREEN — the brief is information: no model, no rank, no direction")
    return 0


def _drive(brief_main, runner, want_json: bool = False):
    """Run the brief end to end against stubs. Returns (rc, err[, payload])."""
    import tempfile
    from data import sources, macro_cal, earnings_cal, price_data
    from report import telegram
    from store import db

    saved = {}

    def patch(mod, name, fn):
        saved[(mod, name)] = getattr(mod, name, None)
        setattr(mod, name, fn)

    tmp = tempfile.mkdtemp(prefix="brief_gate_")
    payload = None
    try:
        patch(sources, "fetch_all", lambda *a, **k: [])
        patch(macro_cal, "fetch_macro", lambda *a, **k: [_Macro("CPI", "08:30")])
        patch(earnings_cal, "fetch_earnings",
              lambda *a, **k: [_Earn("AAL", dt.date(2026, 10, 1))])
        patch(price_data, "fetch_prices", lambda *a, **k: {})
        patch(telegram, "send", lambda *a, **k: True)
        patch(db, "init_db", lambda *a, **k: None)
        patch(db, "connect", lambda *a, **k: None)
        os.environ["DTP_REPORT_JSON"] = os.path.join(tmp, "report.json")

        class _Sec:
            anthropic_key = finnhub_key = alphavantage_key = "x"
            marketaux_key = telegram_token = telegram_chat = "x"

        tier = config.active_tier()
        try:
            rc = runner(tier, _Sec(), True)
            err = ""
        except AssertionError as exc:
            rc, err = 1, str(exc)
        except Exception as exc:                                  # noqa: BLE001
            rc, err = 1, f"{type(exc).__name__}: {exc}"
        p = os.environ["DTP_REPORT_JSON"]
        if want_json and os.path.exists(p):
            payload = json.load(open(p))
    finally:
        for (mod, name), old in saved.items():
            if old is not None:
                setattr(mod, name, old)
        os.environ.pop("DTP_REPORT_JSON", None)
    return (rc, err, payload) if want_json else (rc, err)


if __name__ == "__main__":
    sys.exit(main())
