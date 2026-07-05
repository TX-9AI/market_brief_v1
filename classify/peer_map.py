# market_brief/classify/peer_map.py — market_brief_v1.0.0
"""
Static peer/sector expansion.

The LLM decides ONE thing about scope: "is this story sector-wide (SECTOR)
or company-specific (ISOLATED)?" It never enumerates peers. That mapping is
deterministic and lives here, so the Sonnet prompt stays narrow and cheap
and the peer set is auditable/versionable.

Last updated: 2026-07-04
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
    # loose aliases the model tends to produce
    aliases = {
        "TECH": "MEGA_TECH", "TECHNOLOGY": "MEGA_TECH", "SOFTWARE": "MEGA_TECH",
        "SEMICONDUCTOR": "SEMIS", "SEMICONDUCTORS": "SEMIS", "CHIPS": "SEMIS",
        "OIL": "ENERGY", "OIL_AND_GAS": "ENERGY", "ENERGY_MAJORS": "ENERGY",
        "BANKS": "FINANCIALS", "BANKING": "FINANCIALS", "FINANCIAL": "FINANCIALS",
        "HEALTH": "HEALTHCARE", "PHARMA": "HEALTHCARE", "PHARMACEUTICAL": "HEALTHCARE",
        "RETAIL": "CONSUMER", "CONSUMER_DISCRETIONARY": "CONSUMER",
        "BONDS": "RATES_MACRO", "RATES": "RATES_MACRO", "GOLD": "RATES_MACRO",
    }
    return aliases.get(key)
