#!/usr/bin/env python3
# market_brief/tests/check_panel.py — market_brief_v1.0.0
"""
The brief's universe must BE the fleet. This checks that, by execution.

v1.0.0 — 2026-08-20 — written with the config v1.6.0 panel collapse.

WHY IT EXISTS. `config.UNIVERSE` and `day_trader_pro/selector.py::PANEL` name
the same fifteen boxes in two repositories. Two files claiming one job is the
failure this project keeps finding in its own code: whichever gets updated
becomes the truth and the other rots quietly, and the symptom is a morning
brief that scores a name with no box — or worse, silently stops scoring one
that has a box.

⚠️ IT IS A PLAIN SCRIPT WITH AN EXIT CODE, NOT A PYTEST FILE. A verification
that goes red on ENVIRONMENT rather than CONTENT teaches an operator to ignore
reds.

⚠️ EVERY CHECK BELOW EXECUTES THE CODE IT IS ABOUT. None of them greps source
text. C4 in particular drives `compute_composites` with an off-panel record and
asserts the composite is absent — a source-text check would have passed against
the pre-fix code, which is exactly how a scored terminated box would have
shipped.

BORN RED, both directions, verified 2026-08-20 against the pristine repo:
  C1 -> 29-name universe, "UNIVERSE has 29 names, expected 15"
  C4 -> "AAPL was SCORED - the off-panel filter is not running"

Run:  cd ~/market-brief && python3 tests/check_panel.py     (exit 0 == green)
"""

from __future__ import annotations

import datetime as dt
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config                                    # noqa: E402
from classify import peer_map                    # noqa: E402
from report import emit                          # noqa: E402
from score.aggregate import compute_composites   # noqa: E402

# The fleet, as pinned in day_trader_pro/selector.py::PANEL (panel v2,
# 2026-08-20). When the panel changes, BOTH repos change in the same commit and
# this literal is the thing that notices if only one did.
SELECTOR_PANEL = [
    "NVDA", "SPX", "PLTR", "MU", "QQQ", "GOOGL", "AMZN", "AVGO",
    "TSLA", "META", "NFLX", "CRM", "UNH", "CVX", "AMD",
]

PROBLEMS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    # detail is the FAILURE explanation and prints only on a red. Printing it
    # beside a PASS produced lines reading "PASS  AAPL was SCORED" - a green
    # board carrying the text of the defect it just cleared.
    print(f"  {'PASS' if ok else 'FAIL'}  {name}"
          + (f"  - {detail}" if (detail and not ok) else ""))
    if not ok:
        PROBLEMS.append(name)


def main() -> int:
    print("=" * 68)
    print("CHECK PANEL: the brief's universe is the fleet")
    print("=" * 68)

    # ── C1 the mirror ────────────────────────────────────────────────────
    uni = list(config.UNIVERSE)
    check("C1 universe size", len(uni) == len(SELECTOR_PANEL),
          f"UNIVERSE has {len(uni)} names, expected {len(SELECTOR_PANEL)}")
    missing = sorted(set(SELECTOR_PANEL) - set(uni))
    extra = sorted(set(uni) - set(SELECTOR_PANEL))
    check("C1 universe == selector.PANEL", not missing and not extra,
          f"missing={missing} extra={extra}" if (missing or extra) else "")
    check("C1 no duplicate names", len(uni) == len(set(uni)))

    # ── C2 sector table integrity ────────────────────────────────────────
    members = {t for m in config.SECTORS.values() for t in m}
    orphans = sorted(members - set(uni))
    check("C2 no sector member off the panel", not orphans, f"orphans={orphans}")
    empties = sorted(k for k, m in config.SECTORS.items() if not m)
    check("C2 no empty sector label", not empties, f"empty={empties}")
    uncovered = sorted(set(uni) - members)
    check("C2 every panel name has a sector", not uncovered,
          f"uncovered={uncovered}")

    # ── C3 alias resolution cannot name a dead sector ────────────────────
    # Executed against the real resolver, not the alias literal.
    dead = [a for a in ("BANKS", "BANKING", "FINANCIAL", "BONDS", "RATES", "GOLD")
            if peer_map.resolve_sector_name(a) is not None]
    check("C3 retired-sector aliases resolve to None", not dead,
          f"still resolving: {dead}")
    check("C3 live aliases still resolve",
          peer_map.resolve_sector_name("CHIPS") == "SEMIS"
          and peer_map.resolve_sector_name("PHARMA") == "HEALTHCARE")
    spill = peer_map.peers_for_sector("SEMIS", exclude={"NVDA"})
    check("C3 peer expansion returns panel names only",
          spill and set(spill) <= set(uni), f"peers={spill}")

    # ── C4 THE ONE THAT MATTERS: an off-panel signal is never scored ─────
    # A scheduled run re-reads PERSISTED signals over a 24-96h window, so rows
    # for terminated boxes outlive the config change. Drive the real function.
    now = dt.datetime.now(dt.timezone.utc)

    def _row(tk: str) -> dict:
        return {"ticker": tk, "sentiment": 0.8, "magnitude": 0.9, "weight": 1.0,
                "event_type": "GENERAL", "is_spillover": False,
                "created_utc": now, "one_line": f"{tk} headline"}

    on_panel, off_panel = "NVDA", "AAPL"       # AAPL: terminated 2026-08-20
    comps = compute_composites([_row(on_panel), _row(off_panel)], now,
                               config.TIERS["free"], {})
    scored = {c.ticker for c in comps}
    check("C4 off-panel signal is NOT scored", off_panel not in scored,
          f"{off_panel} was SCORED - the off-panel filter is not running")
    check("C4 on-panel signal still scores", on_panel in scored,
          f"{on_panel} vanished - the filter is too aggressive")

    # ── C5 the report ranks every panel name ─────────────────────────────
    tickers = [{"ticker": t, "score": 0.5 - i * 0.01, "direction": "BULLISH",
                "conviction": 0.5, "earnings_this_week": False}
               for i, t in enumerate(uni)]
    ranked = emit._move_ranked(tickers, set(), False, [])
    check("C5 move_ranked covers the whole panel", len(ranked) == len(uni),
          f"ranked {len(ranked)} of {len(uni)}")
    check("C5 move_ranked names are all on the panel",
          {r["ticker"] for r in ranked} <= set(uni))

    print("=" * 68)
    if PROBLEMS:
        print(f"  {len(PROBLEMS)} problem(s): {PROBLEMS}")
        print("  The brief's universe and the fleet disagree. A name scored")
        print("  here with no box is spend with no reader; a box missing here")
        print("  is a trader the morning report never mentions.")
        return 1
    print(f"  ALL GREEN - {len(uni)} names, universe == fleet")
    return 0


if __name__ == "__main__":
    sys.exit(main())
