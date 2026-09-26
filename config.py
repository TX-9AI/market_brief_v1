# market_brief/config.py — market_brief_v1.8.0
"""
Central configuration for the Vertigo Capital news/Pre-market Brief.

Single source of truth for:
  - the traded universe (mega-cap, deep-liquid-options only)
  - tier feature-gating (free / mid / premium) as ONE switch
  - per-event-type decay half-lives
  - magnitude thresholds that drive the Haiku->Sonnet cascade
  - env-var names for all secrets (nothing sensitive is committed)

Nothing in this file should ever contain a live API key or bot token.
All secrets are read from the environment at runtime (see load_secrets()).

v1.8.0 — 2026-09-26 — Secrets gains `fred_key` (FRED_API_KEY). Free key from
         fred.stlouisfed.org/docs/api/api_key.html; it is the macro calendar's
         only input and the section names itself dark without it.
v1.7.0 — 2026-09-26 — PANEL 15 -> 17. AAL and SOFI joined the fleet on
         2026-09-24 and traded from 2026-09-25. ⚠️ THIS REPO WAS A FOURTH
         MIRROR OF THE PANEL AND NOTHING PINNED IT: r423 took the fleet to 17
         in three places and left this one at 15, so for one session the brief
         polled fifteen of the seventeen boxes it is supposed to cover. The
         file's own rule — *"a name the fleet cannot trade is a name this
         brief does not poll"* — held; its converse did not. SECTORS gains
         AIRLINES and FINTECH, single-member on purpose (see section 2: a
         manufactured peer would manufacture spillover).
v1.6.0 — 2026-08-20 — UNIVERSE == PANEL. The fleet was pared 29 -> 15 and the
         other 14 instances terminated; the brief was still polling, classifying
         and SCORING all of them. CORE_TRADED/WATCH_EXTRA are gone (one list, so
         two cannot disagree), SECTORS is rebuilt to panel membership with
         FINANCIALS and RATES_MACRO deleted rather than emptied, and an import-
         time invariant refuses a sector member that is not in the universe.
Last updated: 2026-08-20
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# 1. UNIVERSE == THE PANEL  (the boxes that actually exist)
# --------------------------------------------------------------------------
# v1.6.0 (2026-08-20) — THE UNIVERSE IS NOW THE FLEET, NOT A WATCHLIST.
#
# WHY. On 2026-08-20 the trading fleet was pared from 29 boxes to 15 and the
# other 14 INSTANCES WERE TERMINATED (AAPL COST DIA GLD GS IWM JPM LLY MSFT
# ORCL SMCI SMH TLT XOM). The brief kept polling all of them: one Finnhub
# request and one Haiku/Sonnet classify pass per name, every morning, for
# tickers with no box, no candle feed and no consumer. That is spend with no
# reader — and worse, those names still landed in `scores`, in `move_ranked`
# and in the Telegram brief, which is a report describing a fleet that no
# longer exists.
#
# ⚠️ SELECTION NO LONGER HAPPENS HERE, AND THAT IS THE POINT. day_trader_pro's
# `selector.PANEL` (hardcoded 2026-08-17, panel v2 2026-08-20) pins the trade
# set; `select()` returns it without consulting this report at all. The brief's
# remaining jobs are (a) WAKE the boxes via the orchestrator's morning run,
# (b) be READ by the operator — macro landmines, Fed day, earnings — and
# (c) score the names that can actually trade. Ranking names that cannot trade
# serves none of the three.
#
# ⚠️ THIS LIST MIRRORS `day_trader_pro/selector.py::PANEL` AND MUST MATCH IT.
# Two files naming the same fleet is the failure this project keeps finding, so
# the mirror is PINNED BY A TEST (`tests/check_panel.py`) rather than by
# comment. When the panel changes, both change in the same commit.
#
# ⚠️ ORDER IS LOAD-BEARING, once. `data/sources.py` uses this order as the
# Alpha Vantage ticker-filter priority and AV is capped at AV_MAX_TICKERS (10)
# because a long ticker list makes the whole AV call fail. Every equity here is
# polled INDIVIDUALLY on Finnhub regardless, so the AV cap costs the tail names
# a supplementary source, never their coverage. The order below is the panel's
# own (ranked by trade count, per selector.py) — not re-sorted here.
PANEL = [
    "NVDA", "SPX", "PLTR", "MU", "QQQ", "GOOGL", "AMZN", "AVGO",
    "TSLA", "META", "NFLX", "CRM", "UNH", "CVX", "AMD",
    # 🔴 2026-09-25 — AAL and SOFI joined the fleet 09-24 and TRADE from today.
    # This repo is a FOURTH mirror of the panel and `test_panel_mirror` does not
    # pin it — it covers otv4, dtp and s3_sweep only — so r423's 15 -> 17 landed
    # in three places and left this one behind. The file's own rule is that "a
    # name the fleet cannot trade is a name this brief does not poll"; the
    # converse is what was broken.
    "AAL", "SOFI",
]

# The screener ranks THIS set. There is no second, wider watchlist: a name the
# fleet cannot trade is a name this brief does not poll, classify, score or
# print.
UNIVERSE = list(PANEL)  # 17 tickers == 17 boxes


# --------------------------------------------------------------------------
# 2. PEER / SECTOR MAP  (static — the LLM only decides "does it spill?",
#    never "who are the peers". Keeps the Sonnet prompt narrow & cheap.)
# --------------------------------------------------------------------------
# sector -> tickers in-universe that belong to it.
# v1.6.0 — rebuilt to panel membership. FINANCIALS (JPM, GS) and RATES_MACRO
# (TLT, GLD) are GONE, not emptied: every member was terminated.
#
# ⚠️ AN EMPTY SECTOR IS WORSE THAN A MISSING ONE. These keys are handed to the
# model as the allowed `scope=SECTOR` labels. A label that survives with no
# members is one the model can legitimately choose, after which peer expansion
# returns nothing and the story evaporates with no error — plausible silence in
# its purest form. A label that does not exist cannot be chosen, and the
# alias table in peer_map is validated against this dict for the same reason.
#
# ⚠️ SINGLE-MEMBER SECTORS ARE CORRECT, NOT BROKEN. ENERGY, HEALTHCARE and
# CONSUMER each have one panel name left. Spillover for them resolves to zero
# peers, which is the true answer — there is nobody left on the fleet to spill
# to — and the label still does its real job of telling the deep pass the story
# is sector-wide rather than company-specific.
#
# ⚠️ AND THE SPILLOVER THE PARING COST IS REAL, RECORDED SO IT IS NOT
# REDISCOVERED AS A BUG. AAPL, MSFT and SMH were never traded but they were the
# mega-tech and semis BELLWETHERS: an Apple story used to spill 0.35 onto
# GOOGL/AMZN/META/NVDA/CRM. Off the universe, an Apple story is not ingested at
# all. Same for SPY into BROAD_INDEX — and SPX is in `_NON_EQUITY`, so it is
# never polled directly and now takes its sector read from QQQ alone.
SECTORS = {
    "MEGA_TECH":   ["NVDA", "AMZN", "GOOGL", "META", "CRM"],
    "SEMIS":       ["NVDA", "MU", "AVGO", "AMD"],
    "ENERGY":      ["CVX"],
    "HEALTHCARE":  ["UNH"],
    "CONSUMER":    ["AMZN"],
    "GROWTH_SPEC": ["TSLA", "PLTR", "NFLX"],
    "BROAD_INDEX": ["QQQ", "SPX"],
    # 2026-09-25 — the two TEST-lineage boxes. Single-member sectors are
    # correct, not broken (see the note above): neither has a peer on this
    # panel, and inventing one would manufacture spillover between names that
    # have no real relationship.
    "AIRLINES":    ["AAL"],
    "FINTECH":     ["SOFI"],
}

# v1.6.0 — DRIFT INVARIANT, checked at import. A sector member that is not in
# the universe produces spillover signals for a ticker nothing else in the run
# will ever score, and it fails silently. This is the one place the two lists
# can diverge, so it is the one place that refuses to start.
_ORPHANS = sorted({t for m in SECTORS.values() for t in m} - set(UNIVERSE))
if _ORPHANS:
    raise ValueError(
        f"config.SECTORS names tickers outside UNIVERSE: {_ORPHANS}. "
        "Update both together — see section 1.")
_EMPTY = sorted(k for k, m in SECTORS.items() if not m)
if _EMPTY:
    raise ValueError(
        f"config.SECTORS has empty sector(s): {_EMPTY}. Delete the key rather "
        "than leaving a label the model can choose and nothing can satisfy.")

# ticker -> its home sector(s), derived from SECTORS (spillover uses this).
def _build_ticker_sectors() -> dict[str, list[str]]:
    out: dict[str, list[str]] = {t: [] for t in UNIVERSE}
    for sector, members in SECTORS.items():
        for t in members:
            if t in out:
                out[t].append(sector)
    return out

TICKER_SECTORS = _build_ticker_sectors()


# --------------------------------------------------------------------------
# 3. DECAY  (per-event-type half-life in HOURS — not one global constant)
# --------------------------------------------------------------------------
# A macro print is priced within hours; an M&A rumor bleeds over days.
HALF_LIFE_HOURS = {
    "MACRO":        6.0,    # CPI/NFP/FOMC — decays fast once digested
    "EARNINGS":     36.0,
    "MNA_RUMOR":    72.0,
    "GUIDANCE":     48.0,
    "ANALYST":      24.0,
    "REGULATORY":   60.0,
    "PRODUCT":      30.0,
    "GENERAL":      18.0,   # default bucket
}
DEFAULT_HALF_LIFE = HALF_LIFE_HOURS["GENERAL"]


# --------------------------------------------------------------------------
# 4. WEIGHTING
# --------------------------------------------------------------------------
DIRECT_MENTION_WEIGHT = 1.00     # ticker named in the article
SECTOR_SPILLOVER_WEIGHT = 0.35   # discounted peer bleed
CLUSTER_SIZE_CAP = 8             # coverage weight saturates (log-ish) here:
                                 # per-ticker article count above this adds no
                                 # further coverage bonus.


# --------------------------------------------------------------------------
# 5. CASCADE THRESHOLDS  (drive Haiku -> Sonnet escalation)
# --------------------------------------------------------------------------
# An event escalates to Sonnet (mid tier) only if it maps to the universe
# AND clears this magnitude floor. Premium sends everything mapped to Sonnet.
SONNET_MAGNITUDE_FLOOR = 0.45    # 0..1 magnitude from Haiku triage
INTRADAY_SHOCK_FLOOR = 0.75      # premium break-alert trigger (|sent|*mag)

# --------------------------------------------------------------------------
# 5b. POLITICAL / SOCIAL SHOCK  ([platinum] only)
# --------------------------------------------------------------------------
# A single Trump post can gap the index in seconds. Platinum pushes a
# volatility WARNING (not a front-run — retail polling won't beat the algos).
# Only market-relevant posts clearing this magnitude floor alert.
POLITICAL_SHOCK_FLOOR = 0.60     # 0..1 market-impact magnitude to alert
POLITICAL_HANDLE = "realDonaldTrump"
# Free default: CNN-hosted archive of Trump's Truth Social posts (~5-min
# refresh). Community archives can go dark, so this is override-able and the
# fetch degrades gracefully. Point POLITICAL_PUSH_ENDPOINT at a paid
# low-latency feed (e.g. a WebSocket bridge) for true real-time on platinum.
POLITICAL_ARCHIVE_URL = os.environ.get(
    "POLITICAL_ARCHIVE_URL",
    "https://ix.cnn.io/data/truth-social/truth_archive.json")
POLITICAL_PUSH_ENDPOINT = os.environ.get("POLITICAL_PUSH_ENDPOINT", "")
POLITICAL_MAX_POSTS = 40         # cap per scan

# --------------------------------------------------------------------------
# 5c. SIGNAL VALIDATION — price data  ([premium]/[platinum] only)
# --------------------------------------------------------------------------
# Compares composite scores to what price actually did afterward, using
# Yahoo Finance's UNOFFICIAL chart endpoint (Yahoo has no official public
# API — it was shut down in 2017). Backend-only: powers the trailing
# hit-rate in the report footer, never surfaced as a quote/chart feature.
# No SLA, no documented rate limit, can break or get throttled without
# notice, data delayed ~15-20 min. See data/price_data.py for the caveats.
VALIDATION_HORIZON_HOURS = 24     # measure forward return this many hours out
VALIDATION_MAX_TICKERS = 10       # cap price lookups per run (be a light citizen)
YAHOO_CHART_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{symbol}"


# --------------------------------------------------------------------------
# 6. TIERS  (the whole product ladder lives here — ONE switch)
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class TierSpec:
    name: str
    triage_model: str
    deep_model: str | None          # None => no Sonnet pass at all
    deep_on_everything: bool        # premium: skip the magnitude gate
    surprise_term: bool             # sentiment delta vs trailing baseline
    llm_spillover: bool             # True=Sonnet reasons; False=static flat
    sources: tuple[str, ...]
    json_output: bool               # write machine-readable row for the suite
    intraday_alerts: bool
    validation: bool                # log signal vs forward realized move
    political_feed: bool = False    # [platinum] Trump/Truth Social shock alerts


HAIKU = "claude-haiku-4-5"
SONNET = "claude-sonnet-5"

TIERS: dict[str, TierSpec] = {
    "free": TierSpec(
        name="free",
        triage_model=HAIKU,
        deep_model=None,
        deep_on_everything=False,
        surprise_term=False,
        llm_spillover=False,
        sources=("finnhub", "alphavantage"),
        json_output=False,
        intraday_alerts=False,
        validation=False,
    ),
    "mid": TierSpec(
        name="mid",
        triage_model=HAIKU,
        deep_model=SONNET,
        deep_on_everything=False,        # escalate only high-magnitude events
        surprise_term=True,
        llm_spillover=True,
        sources=("finnhub", "alphavantage"),
        json_output=True,
        intraday_alerts=False,
        validation=False,
    ),
    "premium": TierSpec(
        name="premium",
        triage_model=HAIKU,
        deep_model=SONNET,
        deep_on_everything=True,         # Sonnet reviews every mapped event
        surprise_term=True,
        llm_spillover=True,
        sources=("finnhub", "alphavantage", "benzinga"),
        json_output=True,
        intraday_alerts=True,
        validation=True,
        political_feed=False,
    ),
    "platinum": TierSpec(
        name="platinum",
        triage_model=HAIKU,
        deep_model=SONNET,
        deep_on_everything=True,
        surprise_term=True,
        llm_spillover=True,
        sources=("finnhub", "alphavantage", "benzinga"),
        json_output=True,
        intraday_alerts=True,
        validation=True,
        political_feed=True,             # <-- the platinum differentiator
    ),
}


def active_tier() -> TierSpec:
    """Resolve the running tier from env (SCREENER_TIER), default 'free'."""
    key = os.environ.get("SCREENER_TIER", "free").strip().lower()
    if key not in TIERS:
        raise ValueError(
            f"SCREENER_TIER='{key}' invalid. Choose one of: {list(TIERS)}"
        )
    return TIERS[key]


# --------------------------------------------------------------------------
# 6b. MACRO CALENDAR — web-search fallback  (ALL tiers)
# --------------------------------------------------------------------------
# Finnhub's structured economic-calendar endpoint is gated behind a paid plan
# (confirmed via live 403 "you don't have access to this resource" on a free
# key) — separate from the free news API. Rather than pay for that add-on or
# leave the macro/landmines section permanently empty, this falls back to a
# web-search-grounded LLM call whenever the structured source comes back
# empty. The calendar itself is public knowledge published months ahead by
# the BLS/BEA/Fed; the web search is what lets same-day actual-vs-forecast
# prints show up instead of relying on stale training-data knowledge.
#
# Runs on EVERY tier — this is calendar fact-retrieval, not the news-
# sentiment cascade, so it isn't gated behind a paid screener tier the way
# Sonnet-deep-pass features are. Cost is a flat $0.01/search (up to
# MACRO_WEB_MAX_SEARCHES per call) plus normal token costs — a few cents/day
# worst case, once daily. Set to Sonnet: on a fact where being wrong (e.g.
# the wrong FOMC date) is more costly than the token-price difference,
# accuracy wins over the negligible per-day savings Haiku would offer here.
MACRO_WEB_MODEL = SONNET
MACRO_WEB_MAX_SEARCHES = 4


# --------------------------------------------------------------------------
# 7. SECRETS  (env-only; never hardcode)
# --------------------------------------------------------------------------
@dataclass
class Secrets:
    anthropic_key: str = ""
    finnhub_key: str = ""
    alphavantage_key: str = ""
    benzinga_key: str = ""
    fred_key: str = ""
    telegram_token: str = ""
    telegram_chat_id: str = ""


def load_env_file(path: str | None = None) -> str | None:
    """Load KEY=VALUE lines from a .env into os.environ for manual runs.

    The REAL environment always wins — we only set a key if it isn't already
    present — so systemd's EnvironmentFile= is never overridden. Looks in an
    explicit path, then the CWD, then this file's directory. Returns the path
    loaded, or None. This is why `python main.py --config` works from the
    install dir without `source .env` first.
    """
    candidates = [
        path,
        os.path.join(os.getcwd(), ".env"),
        os.path.join(os.path.dirname(os.path.abspath(__file__)), ".env"),
    ]
    for p in candidates:
        if not p or not os.path.isfile(p):
            continue
        with open(p) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                key, _, val = line.partition("=")
                key = key.strip()
                val = val.strip().strip('"').strip("'")
                if key and key not in os.environ:
                    os.environ[key] = val
        return p
    return None


def load_secrets() -> Secrets:
    return Secrets(
        anthropic_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        finnhub_key=os.environ.get("FINNHUB_API_KEY", ""),
        alphavantage_key=os.environ.get("ALPHAVANTAGE_API_KEY", ""),
        benzinga_key=os.environ.get("BENZINGA_API_KEY", ""),
        # v1.8.0 — FRED. Free key: fred.stlouisfed.org/docs/api/api_key.html
        fred_key=os.environ.get("FRED_API_KEY", ""),
        telegram_token=os.environ.get("TELEGRAM_BOT_TOKEN", ""),
        # Jason's existing chat id is a safe default; token is still env-only.
        telegram_chat_id=os.environ.get("TELEGRAM_CHAT_ID", "6075312586"),
    )


# --------------------------------------------------------------------------
# 8. RUNTIME PATHS / MISC
# --------------------------------------------------------------------------
DB_PATH = os.environ.get("SCREENER_DB", os.path.expanduser("~/market-brief/screener.db"))
REPORT_TZ = "America/New_York"
REPORT_HOUR = 9
REPORT_MINUTE = 15
LOOKBACK_HOURS = 24          # how far back a scheduled run ingests
DRY_RUN = os.environ.get("SCREENER_DRY_RUN", "0") == "1"   # print instead of send
HTTP_TIMEOUT = 20

# Per-call ceiling on an Anthropic request (seconds). A hung call fails fast and
# is retried by the client wrapper rather than stalling the whole run. This is
# the durability fix — one slow API call can never block the brief again.
LLM_TIMEOUT_S = 30

# The per-ticker classify pass runs the ~29 names CONCURRENTLY. This bounds how
# many Anthropic calls are in flight at once (thread pool size).
LLM_MAX_WORKERS = 12
