# market_brief/classify/peer_map.py — market_brief_v1.1.0
"""
Static peer/sector expansion.

The LLM decides ONE thing about scope: "is this story sector-wide (SECTOR)
or company-specific (ISOLATED)?" It never enumerates peers. That mapping is
deterministic and lives here, so the Sonnet prompt stays narrow and cheap
and the peer set is auditable/versionable.

v1.1.0 — 2026-08-20 — alias resolution validated against config.SECTORS, so a
         sector deleted with the panel collapse cannot resolve to a live-looking
         key with no members.
Last updated: 2026-08-20
"""

from __future__ import annotations

import config


def peers_for(ticker: str, exclude_self: bool = True) -> list[str]:
    """All in-universe tickers sharing a sector with `ticker`."""
    sectors = config.TICKER_SECTORS.get(ticker, [])
    out: set[str] = set()
    for s in sectors:
        out.update(config.SECTORS.get(s, []))
    if exclude_self:
        out.discard(ticker)
    return sorted(out)


def peers_for_sector(sector: str, exclude: set[str] | None = None) -> list[str]:
    """All in-universe tickers in a named sector, minus `exclude`."""
    members = set(config.SECTORS.get(sector, []))
    if exclude:
        members -= exclude
    return sorted(members)


def resolve_sector_name(raw: str) -> str | None:
    """
    Map a free-text sector label from the LLM to a known SECTORS key.
    Returns None if we can't confidently place it (spillover then skipped).
    """
    if not raw:
        return None
    key = raw.strip().upper().replace(" ", "_")
    if key in config.SECTORS:
        return key
    # loose aliases the model tends to produce. Kept deliberately WIDER than
    # config.SECTORS — the model does not know which sectors still have members
    # on the fleet, and an alias for a retired sector is not a spelling the
    # table should forget.
    aliases = {
        "TECH": "MEGA_TECH", "TECHNOLOGY": "MEGA_TECH", "SOFTWARE": "MEGA_TECH",
        "SEMICONDUCTOR": "SEMIS", "SEMICONDUCTORS": "SEMIS", "CHIPS": "SEMIS",
        "OIL": "ENERGY", "OIL_AND_GAS": "ENERGY", "ENERGY_MAJORS": "ENERGY",
        "BANKS": "FINANCIALS", "BANKING": "FINANCIALS", "FINANCIAL": "FINANCIALS",
        "HEALTH": "HEALTHCARE", "PHARMA": "HEALTHCARE", "PHARMACEUTICAL": "HEALTHCARE",
        "RETAIL": "CONSUMER", "CONSUMER_DISCRETIONARY": "CONSUMER",
        "BONDS": "RATES_MACRO", "RATES": "RATES_MACRO", "GOLD": "RATES_MACRO",
    }
    # v1.1.0 — RESOLVE AGAINST THE LIVE SECTOR TABLE, NOT THE ALIAS TABLE.
    # config v1.6.0 deleted FINANCIALS and RATES_MACRO (every member was on a
    # terminated box). Without this line "BANKS" still resolved to the string
    # "FINANCIALS", scope stayed SECTOR with spills_over=True, and peer lookup
    # returned an empty list — a story recorded as spilling into a sector that
    # does not exist. Returning None is the honest answer and it is the value
    # scope.py already handles: it turns spillover OFF rather than on to nobody.
    resolved = aliases.get(key)
    return resolved if resolved in config.SECTORS else None
