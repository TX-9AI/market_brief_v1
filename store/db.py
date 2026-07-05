# market_brief/store/db.py — market_brief_v1.3.0
"""
SQLite persistence.

Tables:
  signals         — one classified (ticker, sentiment, magnitude, weight) row
  macro_events    — scheduled red-folder events (kept separate from signals)
  earnings_events — watched-name earnings this week (session + estimate)
  composites      — per-ticker composite snapshot at report time
  reports         — sent-report ledger (drives 'since last report' windowing)
  validation      — [premium/platinum] signal vs forward realized move
                    (price_at_signal added via additive migration in init_db)
  alerted_events  — dedup ledger so an intraday/political shock pings ONCE

WAL is enabled for concurrent read during writes. The .db-wal / .db-shm
sidecar files are excluded from git and tarballs (see .gitattributes / tar
exclude list in deploy/install.sh).

Last updated: 2026-07-04
"""

from __future__ import annotations

import datetime as dt
import json
import os
import sqlite3
from typing import Any, Iterable

import config

_SCHEMA = """
CREATE TABLE IF NOT EXISTS signals (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    ticker        TEXT NOT NULL,
    sentiment     REAL NOT NULL,
    magnitude     REAL NOT NULL,
    weight        REAL NOT NULL,
    event_type    TEXT NOT NULL,
    scope         TEXT NOT NULL,
    is_spillover  INTEGER NOT NULL,
    model_used    TEXT NOT NULL,
    confidence    REAL NOT NULL,
    cluster_id    INTEGER,
    one_line      TEXT,
    rationale     TEXT,
    tier          TEXT NOT NULL,
    created_utc   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_signals_created ON signals(created_utc);
CREATE INDEX IF NOT EXISTS idx_signals_ticker  ON signals(ticker);

CREATE TABLE IF NOT EXISTS macro_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    event_type    TEXT NOT NULL,
    label         TEXT NOT NULL,
    release_utc   TEXT NOT NULL,
    magnitude     REAL NOT NULL,
    actual        TEXT,
    forecast      TEXT,
    previous      TEXT,
    created_utc   TEXT NOT NULL,
    UNIQUE(event_type, release_utc)
);

CREATE TABLE IF NOT EXISTS earnings_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol        TEXT NOT NULL,
    earn_date     TEXT NOT NULL,
    session       TEXT NOT NULL,
    eps_estimate  REAL,
    created_utc   TEXT NOT NULL,
    UNIQUE(symbol, earn_date)
);

CREATE TABLE IF NOT EXISTS composites (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date    TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    score          REAL NOT NULL,
    direction      TEXT NOT NULL,
    surprise_delta REAL,
    conviction     REAL,
    tier           TEXT NOT NULL,
    created_utc    TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_comp_ticker ON composites(ticker);

CREATE TABLE IF NOT EXISTS reports (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    report_date  TEXT NOT NULL,
    tier         TEXT NOT NULL,
    cutoff_utc   TEXT NOT NULL,
    sent_utc     TEXT NOT NULL,
    bluf_json    TEXT
);

CREATE TABLE IF NOT EXISTS validation (
    id             INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id      INTEGER,
    ticker         TEXT NOT NULL,
    signal_score   REAL NOT NULL,
    horizon_hours  INTEGER NOT NULL,
    forward_return REAL,
    created_utc    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alerted_events (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    event_key   TEXT NOT NULL UNIQUE,
    kind        TEXT NOT NULL,
    created_utc TEXT NOT NULL
);
"""


def _iso(d: dt.datetime) -> str:
    if d.tzinfo is None:
        d = d.replace(tzinfo=dt.timezone.utc)
    return d.astimezone(dt.timezone.utc).isoformat()


def _parse(s: str) -> dt.datetime:
    d = dt.datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=dt.timezone.utc)


def connect() -> sqlite3.Connection:
    os.makedirs(os.path.dirname(config.DB_PATH), exist_ok=True)
    con = sqlite3.connect(config.DB_PATH)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    return con


def init_db() -> None:
    con = connect()
    try:
        con.executescript(_SCHEMA)
        _migrate(con)
        con.commit()
    finally:
        con.close()


def _migrate(con: sqlite3.Connection) -> None:
    """Additive-only migrations for installs created before a schema change.
    Currently: adds validation.price_at_signal (needed to compute forward
    return without a second historical-price lookup)."""
    cols = {r["name"] for r in con.execute("PRAGMA table_info(validation)").fetchall()}
    if "price_at_signal" not in cols:
        con.execute("ALTER TABLE validation ADD COLUMN price_at_signal REAL")


# --------------------------------------------------------------------------
# writes
# --------------------------------------------------------------------------
def insert_signals(con: sqlite3.Connection, signals: Iterable, tier: str,
                   now: dt.datetime) -> int:
    rows = [(
        s.ticker, s.sentiment, s.magnitude, s.weight, s.event_type, s.scope,
        1 if s.is_spillover else 0, s.model_used, s.confidence, s.cluster_id,
        s.one_line, s.rationale, tier, _iso(now),
    ) for s in signals]
    con.executemany(
        """INSERT INTO signals
           (ticker,sentiment,magnitude,weight,event_type,scope,is_spillover,
            model_used,confidence,cluster_id,one_line,rationale,tier,created_utc)
           VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", rows)
    con.commit()
    return len(rows)


def insert_macro(con: sqlite3.Connection, events: Iterable, now: dt.datetime) -> int:
    n = 0
    for e in events:
        con.execute(
            """INSERT OR IGNORE INTO macro_events
               (event_type,label,release_utc,magnitude,actual,forecast,previous,created_utc)
               VALUES (?,?,?,?,?,?,?,?)""",
            (e.event_type, e.label, _iso(e.release_utc), e.magnitude,
             e.actual, e.forecast, e.previous, _iso(now)))
        n += 1
    con.commit()
    return n


def insert_earnings(con: sqlite3.Connection, events: Iterable, now: dt.datetime) -> int:
    n = 0
    for e in events:
        con.execute(
            """INSERT OR IGNORE INTO earnings_events
               (symbol,earn_date,session,eps_estimate,created_utc)
               VALUES (?,?,?,?,?)""",
            (e.symbol, e.date.isoformat(), e.session, e.eps_estimate, _iso(now)))
        n += 1
    con.commit()
    return n


def insert_composites(con: sqlite3.Connection, comps: Iterable, report_date: str,
                     tier: str, now: dt.datetime) -> None:
    rows = [(report_date, c.ticker, c.score, c.direction, c.surprise_delta,
             c.conviction, tier, _iso(now)) for c in comps]
    con.executemany(
        """INSERT INTO composites
           (report_date,ticker,score,direction,surprise_delta,conviction,tier,created_utc)
           VALUES (?,?,?,?,?,?,?,?)""", rows)
    con.commit()


def record_report(con: sqlite3.Connection, report_date: str, tier: str,
                 cutoff: dt.datetime, now: dt.datetime, bluf: Any) -> None:
    con.execute(
        """INSERT INTO reports (report_date,tier,cutoff_utc,sent_utc,bluf_json)
           VALUES (?,?,?,?,?)""",
        (report_date, tier, _iso(cutoff), _iso(now), json.dumps(bluf)))
    con.commit()


# --------------------------------------------------------------------------
# reads
# --------------------------------------------------------------------------
def last_report_cutoff(con: sqlite3.Connection, default_lookback_h: int) -> dt.datetime:
    row = con.execute(
        "SELECT sent_utc FROM reports ORDER BY id DESC LIMIT 1").fetchone()
    if row:
        return _parse(row["sent_utc"])
    return dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=default_lookback_h)


def signals_since(con: sqlite3.Connection, since: dt.datetime) -> list[dict[str, Any]]:
    cur = con.execute(
        "SELECT * FROM signals WHERE created_utc >= ? ORDER BY created_utc",
        (_iso(since),))
    out = []
    for r in cur.fetchall():
        d = dict(r)
        d["created_utc"] = _parse(d["created_utc"])
        d["is_spillover"] = bool(d["is_spillover"])
        out.append(d)
    return out


def macro_for_day(con: sqlite3.Connection, day: dt.date) -> list[dict[str, Any]]:
    start = dt.datetime.combine(day, dt.time.min, tzinfo=dt.timezone.utc)
    end = start + dt.timedelta(days=1)
    cur = con.execute(
        "SELECT * FROM macro_events WHERE release_utc >= ? AND release_utc < ? "
        "ORDER BY magnitude DESC", (_iso(start), _iso(end)))
    return [dict(r) for r in cur.fetchall()]


def trailing_baseline(con: sqlite3.Connection, lookback_days: int = 5) -> dict[str, float]:
    """Mean composite per ticker over the last N report snapshots (for surprise)."""
    since = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=lookback_days))
    cur = con.execute(
        "SELECT ticker, AVG(score) AS avg_score FROM composites "
        "WHERE created_utc >= ? GROUP BY ticker", (_iso(since),))
    return {r["ticker"]: r["avg_score"] for r in cur.fetchall()}


# --------------------------------------------------------------------------
# signal validation (backend-only price checks — see data/price_data.py)
# --------------------------------------------------------------------------
def insert_pending_validations(con: sqlite3.Connection, rows: list[dict],
                               now: dt.datetime) -> int:
    """rows: [{ticker, signal_score, price_at_signal, horizon_hours}, ...]"""
    n = 0
    for r in rows:
        con.execute(
            """INSERT INTO validation
               (signal_id,ticker,signal_score,horizon_hours,forward_return,
                price_at_signal,created_utc)
               VALUES (NULL,?,?,?,NULL,?,?)""",
            (r["ticker"], r["signal_score"], r["horizon_hours"],
             r["price_at_signal"], _iso(now)))
        n += 1
    con.commit()
    return n


def due_validations(con: sqlite3.Connection, now: dt.datetime) -> list[dict]:
    """Pending validations (forward_return still NULL) whose horizon has
    elapsed as of `now`. Computed in Python off parsed timestamps rather than
    SQLite date arithmetic, to reuse the same _parse used everywhere else."""
    cur = con.execute(
        "SELECT * FROM validation WHERE forward_return IS NULL "
        "AND price_at_signal IS NOT NULL")
    out = []
    for r in cur.fetchall():
        d = dict(r)
        created = _parse(d["created_utc"])
        if (now - created).total_seconds() / 3600.0 >= d["horizon_hours"]:
            out.append(d)
    return out


def resolve_validation(con: sqlite3.Connection, row_id: int,
                       forward_return: float) -> None:
    con.execute("UPDATE validation SET forward_return = ? WHERE id = ?",
               (forward_return, row_id))
    con.commit()


# --------------------------------------------------------------------------
# dedup ledger (intraday / political shock alerts)
# --------------------------------------------------------------------------
def already_alerted(con: sqlite3.Connection, event_key: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM alerted_events WHERE event_key = ? LIMIT 1",
        (event_key,)).fetchone()
    return row is not None


def mark_alerted(con: sqlite3.Connection, event_key: str, kind: str,
                 now: dt.datetime) -> None:
    con.execute(
        "INSERT OR IGNORE INTO alerted_events (event_key,kind,created_utc) "
        "VALUES (?,?,?)", (event_key, kind, _iso(now)))
    con.commit()
