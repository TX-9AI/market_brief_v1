# market_brief/data/political.py — market_brief_v1.0.0
"""
Political / social shock source — [platinum] only.

Watches Donald Trump's Truth Social posts, which are a distinct market-moving
event class: a single post on tariffs / the Fed / China / a named company can
gap the index in seconds. Platinum uses this to push a VOLATILITY WARNING.

Honesty about latency: the default free source is a community archive with a
~5-minute refresh. That is NOT fast enough to front-run — it's for "a market-
moving post just landed, brace." For true real-time, point
config.POLITICAL_PUSH_ENDPOINT at a paid low-latency feed; this module will
prefer it when set.

Robustness: community archives go dark (the original one did in Oct 2025).
The URL is override-able and every fetch degrades gracefully to [].

Schema (archive JSON): id, created_at (ISO8601), content (HTML), url.

Last updated: 2026-07-04
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass

import requests

import config

_TAG = re.compile(r"<[^>]+>")
_WS = re.compile(r"\s+")


@dataclass
class PoliticalPost:
    id: str
    created_utc: dt.datetime
    text: str
    url: str


def _strip_html(raw: str) -> str:
    if not raw:
        return ""
    txt = _TAG.sub(" ", raw)
    txt = (txt.replace("&amp;", "&").replace("&quot;", '"')
              .replace("&#39;", "'").replace("&nbsp;", " ")
              .replace("&gt;", ">").replace("&lt;", "<"))
    return _WS.sub(" ", txt).strip()


def _parse_ts(s: str) -> dt.datetime | None:
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        d = dt.datetime.fromisoformat(s)
        return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)
    except ValueError:
        return None


def fetch_political_posts(since: dt.datetime,
                          limit: int | None = None) -> list[PoliticalPost]:
    """Pull posts newer than `since` from the configured archive (or push feed)."""
    limit = limit or config.POLITICAL_MAX_POSTS
    url = config.POLITICAL_PUSH_ENDPOINT or config.POLITICAL_ARCHIVE_URL
    if not url:
        print("[political] no source configured -> skipping")
        return []
    try:
        r = requests.get(url, timeout=config.HTTP_TIMEOUT,
                         headers={"accept": "application/json"})
        r.raise_for_status()
        rows = r.json()
    except Exception as exc:
        print(f"[political] fetch error ({url}): {exc}")
        return []

    if isinstance(rows, dict):                 # some feeds wrap in an object
        rows = rows.get("posts") or rows.get("data") or []

    out: list[PoliticalPost] = []
    for row in rows or []:
        ts = _parse_ts(str(row.get("created_at", "")))
        if ts is None or ts < since:
            continue
        text = _strip_html(str(row.get("content", "")))
        if not text:                           # skip media-only / empty posts
            continue
        out.append(PoliticalPost(
            id=str(row.get("id", "")),
            created_utc=ts,
            text=text,
            url=str(row.get("url", "")),
        ))
    out.sort(key=lambda p: p.created_utc, reverse=True)
    out = out[:limit]
    print(f"[political] {len(out)} new posts since {since.isoformat()}")
    return out
