# market_brief/classify/pipeline.py — market_brief_v1.0.0
"""
The cascade orchestrator — turns clustered events into weighted SIGNAL rows,
gated entirely by the active tier.

    free    : Haiku triage only. Spillover = static flat discount (no reason).
    mid     : Haiku triage -> Sonnet on events clearing SONNET_MAGNITUDE_FLOOR.
              Real ISOLATED/SECTOR reasoning + peer expansion.
    premium : Haiku triage -> Sonnet on EVERY mapped event.

A "signal" is one (ticker, sentiment, magnitude, weight, ...) tuple. Direct
mentions get DIRECT_MENTION_WEIGHT; sector spillover gets the discounted
SECTOR_SPILLOVER_WEIGHT. Cluster size adds a saturating coverage bonus.

Last updated: 2026-07-04
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any

import config
from classify import peer_map, triage as triage_mod, scope as scope_mod
from classify.llm_client import LLMClient


@dataclass
class Signal:
    ticker: str
    sentiment: float
    magnitude: float
    weight: float                 # mention/spillover * coverage
    event_type: str
    scope: str                    # ISOLATED | SECTOR | SPILL
    is_spillover: bool
    model_used: str
    confidence: float
    cluster_id: int
    one_line: str = ""
    rationale: str = ""


def _coverage_bonus(cluster_size: int) -> float:
    """Saturating coverage weight: broad wire pickup => slightly higher weight."""
    capped = min(cluster_size, config.CLUSTER_SIZE_CAP)
    return 1.0 + 0.15 * math.log1p(capped - 1) if capped > 1 else 1.0


def classify_clusters(
    clusters: list[dict[str, Any]],
    client: LLMClient,
    tier: config.TierSpec,
) -> list[Signal]:
    """
    clusters: list of dicts with keys:
        id, canonical_title, body, size, baseline_hint
    Returns a flat list of Signal rows.
    """
    signals: list[Signal] = []

    for cl in clusters:
        cid = cl["id"]
        size = cl.get("size", 1)
        cov = _coverage_bonus(size)

        tri = triage_mod.triage_event(
            client, tier.triage_model,
            cl["canonical_title"], cl.get("body", ""),
            baseline_hint=cl.get("baseline_hint", ""),
        )
        if not tri["tickers"]:
            continue  # nothing in our universe -> drop

        # ---- decide whether to escalate to Sonnet -----------------------
        do_deep = False
        if tier.deep_model is not None:
            if tier.deep_on_everything:
                do_deep = True
            elif tri["magnitude"] >= config.SONNET_MAGNITUDE_FLOOR:
                do_deep = True

        if do_deep:
            deep = scope_mod.deep_assess(
                client, tier.deep_model,
                cl["canonical_title"], cl.get("body", ""), tri,
            )
            model_used = tier.deep_model
            sent, mag = deep["sentiment"], deep["magnitude"]
            conf = deep["confidence"]
            scope_label = deep["scope"]
            spill_tickers = deep["spillover_tickers"] if tier.llm_spillover else []
            rationale = deep["rationale"]
        else:
            model_used = tier.triage_model
            sent, mag = tri["sentiment"], tri["magnitude"]
            conf = 0.5
            scope_label = "ISOLATED"
            rationale = ""
            # free tier: cheap static flat spillover on strong single-name news
            if not tier.llm_spillover and mag >= 0.6:
                spill_tickers = []
                for t in tri["tickers"]:
                    spill_tickers.extend(peer_map.peers_for(t))
                spill_tickers = sorted(set(spill_tickers) - set(tri["tickers"]))
            else:
                spill_tickers = []

        # ---- emit direct-mention signals --------------------------------
        for t in tri["tickers"]:
            signals.append(Signal(
                ticker=t, sentiment=sent, magnitude=mag,
                weight=config.DIRECT_MENTION_WEIGHT * cov,
                event_type=tri["event_type"], scope=scope_label,
                is_spillover=False, model_used=model_used, confidence=conf,
                cluster_id=cid, one_line=tri["one_line"], rationale=rationale,
            ))

        # ---- emit discounted spillover signals --------------------------
        for t in spill_tickers:
            signals.append(Signal(
                ticker=t, sentiment=sent, magnitude=mag,
                weight=config.SECTOR_SPILLOVER_WEIGHT * cov,
                event_type=tri["event_type"], scope="SPILL",
                is_spillover=True, model_used=model_used, confidence=conf * 0.8,
                cluster_id=cid, one_line=tri["one_line"], rationale=rationale,
            ))

    return signals
