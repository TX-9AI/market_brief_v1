# market_brief/data/dedup.py — market_brief_v1.0.0
"""
Dedup / event-clustering.

Wire stories get republished dozens of times with near-identical headlines.
We collapse them to ONE event before classification — this both cuts LLM
calls and gives us a free "coverage" weight (cluster size = how loud the
wire is on this story).

V1 method: normalize titles (strip source tags, punctuation, casing), then
greedy fuzzy grouping via difflib. Cheap, dependency-free, good enough at
~30-name volume. (V2 roadmap swaps in title embeddings for scale.)

Last updated: 2026-07-04
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from difflib import SequenceMatcher
from typing import Any

from data.sources import Article

SIMILARITY_THRESHOLD = 0.82

_STRIP = re.compile(r"[^a-z0-9 ]+")
_WS = re.compile(r"\s+")
# common trailing/leading wire cruft
_SOURCE_TAGS = re.compile(
    r"\b(reuters|bloomberg|marketwatch|benzinga|zacks|motley fool|barron'?s|"
    r"seeking alpha|cnbc|yahoo finance|the fly|pr newswire|business wire|"
    r"globe newswire|update \d+|exclusive)\b", re.IGNORECASE)


def _normalize(title: str) -> str:
    t = _SOURCE_TAGS.sub(" ", title.lower())
    t = _STRIP.sub(" ", t)
    t = _WS.sub(" ", t).strip()
    return t


@dataclass
class Cluster:
    id: int
    canonical_title: str
    body: str
    size: int
    members: list[Article] = field(default_factory=list)
    tickers_hint: list[str] = field(default_factory=list)
    baseline_sentiment: float | None = None

    def to_dict(self) -> dict[str, Any]:
        hint = ""
        if self.tickers_hint:
            hint = "provider-tagged: " + ", ".join(sorted(set(self.tickers_hint)))
            if self.baseline_sentiment is not None:
                hint += f" (baseline sent {self.baseline_sentiment:+.2f})"
        return {
            "id": self.id,
            "canonical_title": self.canonical_title,
            "body": self.body,
            "size": self.size,
            "baseline_hint": hint,
        }


def cluster_articles(articles: list[Article]) -> list[Cluster]:
    """Greedy fuzzy clustering on normalized titles."""
    reps: list[tuple[str, Cluster]] = []   # (normalized_title, cluster)
    next_id = 1

    # longest/most-recent first so the canonical member is the richest one
    ordered = sorted(articles, key=lambda a: (len(a.body), a.published_utc), reverse=True)

    for art in ordered:
        norm = _normalize(art.title)
        if not norm:
            continue
        placed = False
        for rep_norm, cl in reps:
            if _similar(norm, rep_norm):
                cl.members.append(art)
                cl.size += 1
                cl.tickers_hint.extend(art.tickers_hint)
                if cl.baseline_sentiment is None and art.baseline_sentiment is not None:
                    cl.baseline_sentiment = art.baseline_sentiment
                if len(art.body) > len(cl.body):
                    cl.body = art.body
                placed = True
                break
        if not placed:
            cl = Cluster(
                id=next_id, canonical_title=art.title, body=art.body, size=1,
                members=[art], tickers_hint=list(art.tickers_hint),
                baseline_sentiment=art.baseline_sentiment,
            )
            reps.append((norm, cl))
            next_id += 1

    clusters = [cl for _, cl in reps]
    print(f"[dedup] {len(articles)} articles -> {len(clusters)} event clusters")
    return clusters


def _similar(a: str, b: str) -> bool:
    # fast reject on length, then ratio
    if not a or not b:
        return False
    if abs(len(a) - len(b)) / max(len(a), len(b)) > 0.4:
        return False
    return SequenceMatcher(None, a, b).ratio() >= SIMILARITY_THRESHOLD
