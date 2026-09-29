#!/usr/bin/env python3
# market_brief/tests/check_instance_vet.py — market_brief_v1.10.0
"""
The morning brief is vetted against the LIVE instance map. This checks that,
by execution.

v1.0.0 — 2026-09-29 — written with data/instance_map.py. Operator: *"Have the
market report vet on the most current instance map every morning."*

⚠️ EVERY CHECK EXECUTES. V1-V6 drive `instance_map.vet` with a fake EC2 client
built in the shape describe_instances returns; V7 drives the REAL
`main.run_information_brief` with every network source stubbed and asserts the
map's symbols, not the list's, reach the page and report.json. A source-text
check would pass on a vet that was written and never called.

BORN RED on market-brief 0cf83aa (no data/instance_map.py): the import fails
and every check reports it.

Run:  cd ~/market-brief && venv/bin/python tests/check_instance_vet.py
"""
from __future__ import annotations

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PROBLEMS: list[str] = []


def check(name: str, ok: bool, detail: str = "") -> None:
    print(f"  {'PASS' if ok else 'FAIL'}  {name}" + ("" if ok else f"  - {detail}"))
    if not ok:
        PROBLEMS.append(name)


class FakeEC2:
    def __init__(self, boxes=None, boom=False):
        self.boxes, self.boom = boxes or [], boom

    def describe_instances(self, **_kw):
        if self.boom:
            raise RuntimeError("no route to EC2")
        return {"Reservations": [{"Instances": [
            {"State": {"Name": st}, "Tags": [{"Key": "Name", "Value": n}]}
            for n, st in self.boxes]}]}


def main() -> int:
    print("=" * 68)
    print("INSTANCE VET: the brief covers the fleet AWS holds, every morning")
    print("=" * 68)
    try:
        from data import instance_map as im
    except Exception as exc:                                     # noqa: BLE001
        check("V0 data/instance_map.py imports", False, f"{type(exc).__name__}: {exc}")
        print(f"  {len(PROBLEMS)} problem(s): {PROBLEMS}")
        return 1

    uni, note = im.vet(["AAA", "BBB"], FakeEC2([("AAA", "stopped"), ("CCC", "running")]))
    check("V1 a tagged box NOT on the list is briefed, and named",
          "CCC" in uni and "CCC" in note, f"{uni} / {note}")
    check("V2 a listed name with NO box is dropped, and named",
          "BBB" not in uni and "BBB" in note, f"{uni} / {note}")
    check("V2b list order is kept, map extras last", uni == ["AAA", "CCC"], str(uni))

    uni, _ = im.vet(["AAA"], FakeEC2([("AAA", "stopped"), ("DDD", "terminated"),
                                      ("EEE", "shutting-down"), ("FFF", "pending")]))
    check("V3 stopped/pending count; terminated/shutting-down do not",
          uni == ["AAA", "FFF"], str(uni))

    uni, note = im.vet(["AAA"], FakeEC2([("AAA", "stopped"),
                                         (im.REPORTER_NAME, "running")]))
    check("V4 the control box is never briefed", im.REPORTER_NAME not in uni, str(uni))
    check("V4b agreement says so", note.startswith("Vetted"), note)

    uni, note = im.vet(["AAA", "BBB"], FakeEC2(boom=True))
    check("V5 map unreadable -> the list, never empty, and SAID on the page",
          uni == ["AAA", "BBB"] and "UNAVAILABLE" in note, f"{uni} / {note}")
    uni, note = im.vet(["AAA"], FakeEC2([]))
    check("V6 map empty -> the list, and SAID", uni == ["AAA"] and "NO boxes" in note,
          f"{uni} / {note}")

    # ── V7 the real brief path uses the vet ──────────────────────────────
    import config
    import main as brief
    from data import macro_fred, macro_cal, earnings_cal, sources, price_data
    from report import telegram

    saved = dict(uni=list(config.UNIVERSE), vet=im.vet,
                 fm=macro_fred.fetch_macro_fred, mc=macro_cal.fetch_macro,
                 er=earnings_cal.fetch_earnings, fa=sources.fetch_all,
                 fp=price_data.fetch_prices, tg=telegram.send,
                 env=os.environ.get("DTP_REPORT_JSON"))
    sent: list[str] = []
    asked: list[list[str]] = []
    try:
        im.vet = lambda listed, client=None: (["ZZZ", "YYY"], "NOTE-FROM-THE-MAP")
        macro_fred.fetch_macro_fred = lambda *a, **k: []
        macro_cal.fetch_macro = lambda *a, **k: []
        earnings_cal.fetch_earnings = lambda *a, **k: []
        sources.fetch_all = lambda *a, **k: []
        price_data.fetch_prices = lambda t, **k: (asked.append(list(t)) or {})
        telegram.send = lambda text, *a, **k: sent.append(text)
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["DTP_REPORT_JSON"] = os.path.join(tmp, "report.json")
            secrets = config.load_secrets()
            brief.run_information_brief(config.active_tier(), secrets, True)
            payload = json.load(open(os.environ["DTP_REPORT_JSON"]))
        check("V7 prices are asked for the MAP's symbols", asked == [["ZZZ", "YYY"]], str(asked))
        check("V7b report.json carries the map's universe and the vet line",
              payload.get("universe") == ["YYY", "ZZZ"]
              and payload.get("fleet_vet") == "NOTE-FROM-THE-MAP",
              f"universe={payload.get('universe')} fleet_vet={payload.get('fleet_vet')}")
        check("V7c the vet line is ON THE PAGE",
              bool(sent) and "NOTE-FROM-THE-MAP" in sent[0], "not in the sent text")
        check("V7d config.UNIVERSE is the map for downstream readers",
              list(config.UNIVERSE) == ["ZZZ", "YYY"], str(config.UNIVERSE))
    except Exception as exc:                                     # noqa: BLE001
        check("V7 the real brief path runs", False, f"{type(exc).__name__}: {exc}")
    finally:
        config.UNIVERSE = saved["uni"]
        im.vet = saved["vet"]
        macro_fred.fetch_macro_fred, macro_cal.fetch_macro = saved["fm"], saved["mc"]
        earnings_cal.fetch_earnings, sources.fetch_all = saved["er"], saved["fa"]
        price_data.fetch_prices, telegram.send = saved["fp"], saved["tg"]
        if saved["env"] is None:
            os.environ.pop("DTP_REPORT_JSON", None)
        else:
            os.environ["DTP_REPORT_JSON"] = saved["env"]

    print("=" * 68)
    if PROBLEMS:
        print(f"  {len(PROBLEMS)} problem(s): {PROBLEMS}")
        return 1
    print("  ALL GREEN - the brief is the instance map, vetted and said")
    return 0


if __name__ == "__main__":
    sys.exit(main())
