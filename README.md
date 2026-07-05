# VERTIGO CAPITAL Pre-market Brief — v1.0.0

An attention-router for the options suite. It watches a small universe of
mega-cap, deep-options names, scores news + macro, and delivers a ranked
"look here first" Telegram rollup weekdays at **09:15 ET** — so you decide
whether to spin up 3 servers or 8 on a given day, on the *right* symbols.

It is **not** a broad market scanner. It ranks ~30 fixed names by
actionability and hands you the hot handful.

---

## Pipeline

```
ingest (Finnhub/AV/Benzinga)
   -> dedup / event-cluster (collapse wire republishes, size = coverage weight)
   -> cascade classify   Haiku triage  ->  Sonnet deep pass (scope + spillover)
   -> aggregate          per-event-type decay + surprise term
   -> report             BLUF + macro landmines + per-ticker detail
   -> deliver            Telegram (+ JSON for the suite on mid/premium)
```

Two deliberate design calls that differ from a naive build:

1. **Macro is its own tier, never summed into ticker scores.** On a
   CPI/FOMC day, single-name sentiment is *less* reliable (everything
   correlates), so macro shows up as "TODAY'S LANDMINES," separately.
2. **Decay half-life is per event type**, not one global constant. A macro
   print decays in hours; an M&A rumor bleeds over days. See
   `config.HALF_LIFE_HOURS`.

---

## The tier ladder (one switch: `SCREENER_TIER`)

| Capability | free | mid | premium | platinum |
|---|:---:|:---:|:---:|:---:|
| Haiku triage (tickers, sentiment, magnitude) | ✅ | ✅ | ✅ | ✅ |
| Sonnet deep pass (scope, spillover reasoning) | — | high-magnitude only | every mapped event | every mapped event |
| Sector spillover | static flat discount | LLM-reasoned + peer map | LLM-reasoned + peer map | LLM-reasoned + peer map |
| Sentiment **surprise** (Δ vs trailing baseline) | — | ✅ | ✅ | ✅ |
| Benzinga source | — | — | ✅ | ✅ |
| Machine-readable JSON for the suite | — | ✅ | ✅ | ✅ |
| Intraday news-shock alerts | — | — | ✅ | ✅ |
| Signal validation (vs forward move) | — | — | ✅ | ✅ |
| **Political / Trump volatility alerts** | — | — | — | ✅ |
| Est. LLM cost @ ~30 names | pennies/day | cents/day | low $/day | low $/day |

The granularity climb is intentional and visible in the report itself
(tier badge in the header; extra fields appear as you go up). This is the
subscription-value story if you productize it.

Switch tiers by editing `.env` (`SCREENER_TIER=mid`) or per-run:
`python main.py --tier premium --dry-run`.

### Platinum — political / volatility shock alerts

Platinum = everything in Premium **plus** a live watch on Trump's Truth Social
posts, which are a distinct market-moving event class (a single tariff / Fed /
China post can gap the index in seconds). When a post clears the market-impact
magnitude floor, Platinum pushes a **volatility WARNING** to Telegram.

Honesty up front: this is a *warning*, not a front-run. The free default feed
(a CNN-hosted archive, ~5-min refresh) is fine for "a market-moving post just
landed, brace" but will not beat the algos. For true real-time, set
`POLITICAL_PUSH_ENDPOINT` to a paid low-latency feed (e.g. a WebSocket bridge)
— the module prefers it when present. Community archives can go dark, so the
URL is override-able (`POLITICAL_ARCHIVE_URL`) and every fetch degrades to a
no-op rather than crashing the scan.

The classifier is deliberately strict: most Trump posts are political noise
and score zero. Only tariff / Fed / China / energy / named-company posts fire.
Alerts dedup by post ID *and* content hash (he reposts identical text under new
IDs), so one event pings once.

---

## Universe

Core (already traded): SPY QQQ SPX AAPL MU NVDA MSFT TSLA NFLX META ORCL
Added: PLTR JPM GS LLY UNH AMZN GOOGL AVGO AMD SMH XOM CVX IWM DIA TLT GLD CRM COST

Edit `config.UNIVERSE` and keep `config.SECTORS` in lockstep (spillover
reads the sector map).

---

## Install

**One-line curl install (recommended).** Download then run (so tmux + prompts
work — don't pipe straight into bash):

```bash
curl -fsSL https://raw.githubusercontent.com/TX-9AI/market_brief_v1/main/install.sh -o install.sh && bash install.sh
```

The installer relaunches itself in **tmux** (reconnect with `tmux attach -t
deploy` if SSH drops), installs system + Python deps, prompts for your keys
(or runs hands-free if already exported), writes `.env`, enables the **09:15 ET
systemd timer**, runs an offline self-test, cleans up the installer, and drops
you into the venv at the working directory.

**Unattended install (secrets bootstrap).**

```bash
cp bootstrap.example.sh bootstrap.sh   # your copy is gitignored
nano bootstrap.sh                      # fill in REPLACE_ME keys
scp bootstrap.sh ubuntu@YOUR_IP:~
ssh ubuntu@YOUR_IP 'bash bootstrap.sh'
```

`bootstrap.sh` exports your keys and calls the installer, which **shreds** it
during cleanup once the keys are in `.env`. The `.gitignore` ignores every
`bootstrap*.sh` except the `.example` template, so real keys can't be
committed. **Never put real secrets in `bootstrap.example.sh`.**

**Manual / from a tarball** (or Windows -> EC2 via `deploy/deploy_windows.bat`):

```bash
tar xzf market_brief_v1.tar.gz && cd market_brief
chmod +x install.sh && ./install.sh --local     # install from local files, no clone
```

### Private repo
If `TX-9AI/market_brief_v1` is private, set `GITHUB_TOKEN` in `bootstrap.sh`.
The token is then used for all three auth points automatically: the `curl` of
`install.sh` (auth header), the `git clone` (tokened URL), and `push.sh`
(ephemeral tokened push — never written to `.git/config`). Public repos need
no token for install; a token is only needed to *push*.

### Dependencies
Only **`anthropic`** and **`requests`** (`requirements.txt`) — the installer
handles them. No pandas/numpy required; the pipeline uses the standard library
(incl. `difflib` for clustering). Those would only enter in V2 with embedding
clustering.

### Keys you need
- `ANTHROPIC_API_KEY` — required on every tier (all tiers use >= Haiku).
- `FINNHUB_API_KEY` — news + economic/earnings calendars (free tier works).
- `ALPHAVANTAGE_API_KEY` — NEWS_SENTIMENT baseline (free: 25 req/day -> one batched call).
- `TELEGRAM_BOT_TOKEN` — dedicated screener bot; chat id defaults to 6075312586.
- `BENZINGA_API_KEY` — premium/platinum only.

## Testing, preview & dev tools

```bash
python main.py --selftest    # offline: full report format, no keys/network
python main.py --config      # active tier, flags, which keys are set (masked)
python main.py --testfeeds   # hit each data source, print counts (no send)
python main.py --preview     # send a SAMPLE brief + shock to Telegram (bot token only)
python main.py --dry-run     # pull live data, print the real report, don't send
bash devtools.sh             # interactive debug/config console (menu over all of the above + SQLite)
```

`--preview` is the fastest way to judge the **rendered** look on your phone: it
needs only the Telegram bot token and uses synthetic data (no news/LLM keys).
`devtools.sh` wraps everything in a menu — config, feed tests, DB inspection
(signals / composites / macro / earnings / shock ledger), a Telegram ping, tier
switching, timer status, and log tailing.

---

## Roadmap

- **V1 (this):** free/mid/premium tiers, cascade, decay+surprise, macro
  landmines, Telegram BLUF, JSON hook, premium intraday + validation table.
- **V2:** title-embedding clustering (scale beyond fuzzy match); wire the
  JSON output into the options suite's server-spin decision; richer
  Benzinga fields.
- **V3 (trust gate) — partially live:** the `validation` table is now
  populated automatically on premium/platinum (see "Signal validation" below).
  Still required before the signal should influence sizing: enough history to
  trust the hit-rate, and a decision on whether it ever gates automatically
  or stays advisory. Until then it is an attention router only.

---

## Signal validation (premium/platinum)

Each scheduled run: (1) resolves any pending validation entries whose
horizon (`VALIDATION_HORIZON_HOURS`, default 24h) has elapsed, computing the
real forward return and updating the trailing hit-rate; (2) records the
current run's top composites as new pending entries at today's price.

This uses Yahoo Finance's **unofficial** chart endpoint (`data/price_data.py`)
— Yahoo has no official public API (shut down 2017). No SLA, no documented
rate limit, can be throttled or change without notice, data delayed ~15-20
min. Scoped deliberately narrow to manage that: it's backend-only math for
the report footer, never a customer-facing quote/chart feature, and it's
capped to `VALIDATION_MAX_TICKERS` (default 10) lookups/day with a pause
between requests. `SPX` is mapped to Yahoo's `^GSPC` — the same mismatch
that's previously bitten options_trader's ORB fetch, avoided here explicitly.

This module wasn't reachable from the build sandbox (no egress to
`query1.finance.yahoo.com`) — verify live with `python main.py --testfeeds`
on a box with real internet before relying on it.

---

## Macro calendar — web-search fallback (all tiers)

Finnhub's structured economic-calendar endpoint is gated behind a paid plan
(confirmed via a live 403 on a free key — separate product from the free
news API). Rather than pay for that add-on, `main.py` falls back to a
**web-search-grounded LLM call** whenever the structured source comes back
empty: the calendar itself (CPI/PPI/NFP/FOMC dates) is public knowledge
published months ahead by the BLS/BEA/Fed, and grounding the call in a real
search is what lets it also reflect same-day actual-vs-forecast prints
instead of stale training-data knowledge.

Cost: Anthropic's web search tool is $0.01/search (capped at
`MACRO_WEB_MAX_SEARCHES`, default 4) plus normal token costs — a few cents/
day worst case, once daily. Runs on **every tier**, since this is factual
retrieval, not the news-sentiment cascade. Default model is Sonnet
(`config.MACRO_WEB_MODEL`) — on a fact where being wrong (the wrong FOMC
date, an invented number) is worse than a slightly-off sentiment score would
be, accuracy wins over the negligible per-day savings Haiku would offer
here; a one-line swap back to Haiku is fine if cost matters more to you.
Every field is validated the same way the news cascade validates LLM
output — an unrecognized `event_type` is dropped, never guessed.

`python main.py --testfeeds` exercises this automatically whenever Finnhub's
calendar is empty — note that this makes a real, billable Anthropic call.

---

## Conventions followed
Modular (one job per file) · version headers on every file · SQLite + WAL
(sidecars excluded from git/tarball) · systemd · single-file installer (no
two-file subprocess pattern) · `icacls`-first Windows deploy · `*.sh text
eol=lf` · `exec bash` · `push.sh` wrapper · `#file.py` working-backups and
WAL excluded from tarballs · no secrets committed.
