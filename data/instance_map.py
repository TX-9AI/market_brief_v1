# market_brief/data/instance_map.py — market_brief_v1.10.0
"""
THE BRIEF'S SYMBOLS ARE VETTED AGAINST THE LIVE INSTANCE MAP EVERY MORNING.

v1.10.0 — 2026-09-29 — Operator, the evening MU and PLTR were terminated:
*"Have the market report vet on the most current instance map every morning."*

🔴 THE LIST WAS A MIRROR AND THE MAP IS THE FLEET. `config.PANEL` is the fifth
hand-kept copy of which boxes exist; it went stale when AAL and SOFI joined
(v1.7.0) and would have gone stale again with MU and PLTR. Since dtp r423 the
WAKE and the CLOSE both read the instance map (EC2 tag Project=day_trader), so
the brief was the last reader still reciting a list. It now asks AWS, before
anything is fetched, which boxes exist, and briefs exactly those.

🔑 THE MAP WINS, THE LIST ORDERS, AND EVERY DISAGREEMENT IS PRINTED ON THE PAGE.
  · a tagged box the list does not name — BRIEFED, and named: a live box the
    morning report cannot see is the failure this exists to end;
  · a listed name with no box — DROPPED, and named: a retired symbol keeps its
    headlines out of the brief the morning after it goes;
  · order follows `config.PANEL` (the AV ticker-priority order), extras last.
⚠️ NEVER EMPTY. If the map cannot be read, or reads empty, the brief falls back
to the config list and SAYS SO on the page. A brief of nothing is worse than a
brief of the last known fleet, and silence about which one it is is worse
than either.
⚠️ SAME RULE AS dtp ec2ops.describe_by_tag, NOT AN IMPORT OF IT. Terminated
and shutting-down are skipped, stopped boxes COUNT (the brief runs at 09:00,
before the 09:15 wake, when every box is stopped), and the control box is
refused by NAME. The brief does not import the control repo, so the tag and
region are read from the same env names dtp uses, with the same defaults.
"""
from __future__ import annotations

import os

TAG_KEY = os.environ.get("DTP_FLEET_TAG_KEY", "Project")
TAG_VALUE = os.environ.get("DTP_FLEET_TAG_VALUE", "day_trader")
REGION = os.environ.get("DTP_REGION", "us-east-2")
REPORTER_NAME = os.environ.get("DTP_REPORTER_TAG", "1-REPORTER")
_GONE = ("terminated", "shutting-down")


def fleet_names(client=None) -> list[str]:
    """Every live box carrying the fleet tag, by its Name tag."""
    if client is None:
        import boto3
        client = boto3.client("ec2", region_name=REGION)
    resp = client.describe_instances(
        Filters=[{"Name": f"tag:{TAG_KEY}", "Values": [TAG_VALUE]}])
    out = set()
    for res in resp.get("Reservations", []):
        for inst in res.get("Instances", []):
            if (inst.get("State") or {}).get("Name") in _GONE:
                continue
            name = next((t.get("Value") for t in inst.get("Tags") or []
                         if t.get("Key") == "Name"), None)
            if name and name != REPORTER_NAME:
                out.add(name.strip().upper())
    return sorted(out)


def vet(listed: list[str], client=None) -> tuple[list[str], str]:
    """-> (universe to brief, one line for the page). Never an empty universe."""
    listed = [s.upper() for s in listed]
    try:
        live = fleet_names(client)
    except Exception as exc:                                     # noqa: BLE001
        return listed, (f"⚠️ Instance map UNAVAILABLE ({type(exc).__name__}) — "
                        f"briefing the config list of {len(listed)}.")
    if not live:
        return listed, (f"⚠️ Instance map returned NO boxes — briefing the "
                        f"config list of {len(listed)}.")
    extra = [s for s in live if s not in listed]
    gone = [s for s in listed if s not in live]
    universe = [s for s in listed if s in live] + extra
    if not extra and not gone:
        return universe, f"Vetted against the instance map: {len(universe)} boxes."
    parts = [f"⚠️ Instance map differs from the list — briefing the map's "
             f"{len(universe)}"]
    if extra:
        parts.append(f"boxes not on the list, briefed: {', '.join(extra)}")
    if gone:
        parts.append(f"listed with no box, dropped: {', '.join(gone)}")
    return universe, "; ".join(parts) + "."
