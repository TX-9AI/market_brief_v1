# market_brief/config.py — market_brief_v1.5.0
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

Last updated: 2026-07-04
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field


# --------------------------------------------------------------------------
# 1. UNIVERSE  (guaranteed-core = Jason's live options names; rest = movers)
# --------------------------------------------------------------------------
# Kept deliberately small: ~30 mega-caps with deep, liquid weekly options.
# The screener's job is to rank THIS set and surface the hot handful — it is
# not a broad market scanner. Add names here; the peer map below should be
# extended in lockstep.

CORE_TRADED = [  # names Jason already runs in the options suite
    "SPY", "QQQ", "SPX", "AAPL", "MU", "NVDA", "MSFT",
    "TSLA", "NFLX", "META", "ORCL",
]

WATCH_EXTRA = [  # requested additions + high-beta / rate-sensitive movers
    "PLTR",              # requested
    "JPM", "GS",         # big financials (rate-sensitive)
    "LLY", "UNH",        # mega-cap pharma / managed care
    "AMZN", "GOOGL",     # mega tech
    "AVGO", "AMD",       # semis complex
    "SMH",               # semis ETF (sector tell)
    "XOM", "CVX",        # energy majors
    "IWM", "DIA",        # breadth / small-cap + dow
    "TLT",               # long bond proxy (rate regime)
    "GLD",               # gold proxy (macro / risk-off tell)
    "CRM", "COST",       # liquid single-name movers
]

UNIVERSE = CORE_TRADED + WATCH_EXTRA  # ~30 tickers


# --------------------------------------------------------------------------
# 2. PEER / SECTOR MAP  (static — the LLM only decides "does it spill?",
#    never "who are the peers". Keeps the Sonnet prompt narrow & cheap.)
# --------------------------------------------------------------------------
# sector -> tickers in-universe that belong to it.
SECTORS = {
    "MEGA_TECH":   ["AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "ORCL", "CRM"],
    "SEMIS":       ["NVDA", "MU", "AVGO", "AMD", "SMH"],
    "ENERGY":      ["XOM", "CVX"],
    "FINANCIALS":  ["JPM", "GS"],
    "HEALTHCARE":  ["LLY", "UNH"],
    "CONSUMER":    ["COST", "AMZN"],
    "GROWTH_SPEC": ["TSLA", "PLTR", "NFLX"],
    "RATES_MACRO": ["TLT", "GLD"],
    "BROAD_INDEX": ["SPY", "QQQ", "SPX", "IWM", "DIA"],
}

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
CLUSTER_SIZE_CAP = 8             # coverage weight saturates (log-ish) here

# Cap how many clusters reach the (per-cluster) Haiku triage — the cascade's
# bottleneck. On a loud news morning dedup can yield 600+ clusters; classifying
# all of them is hundreds of API round-trips (~17 min wall on 2026-07-08, almost
# all I/O wait). We ALWAYS keep every cluster that maps to the universe
# (non-empty tickers_hint — a free pre-API relevance flag), then fill the rest of
# this budget with the largest untagged clusters by coverage. Set to 0 to
# disable the cap (classify everything, old behavior).
CLASSIFY_MAX_CLUSTERS = 200


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
