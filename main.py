# market_brief/main.py — market_brief_v1.5.0
"""
Orchestrator.

Pipeline (all gating driven by the active tier):
    ingest -> dedup/cluster -> cascade classify -> persist signals
           -> macro lookup -> aggregate (decay + surprise)
           -> build report -> deliver (Telegram) -> record

CLI:
    python main.py                # scheduled 09:15 run (uses env SCREENER_TIER)
    python main.py --tier mid     # override tier for this run
    python main.py --dry-run      # print report, don't send, don't record
    python main.py --intraday     # premium shock-scan (lightweight)
    python main.py --selftest     # offline smoke test, no network/keys

v1.5.0 — 2026-07-05 — emit full-slate report.json for day_trader_pro
         selection (report/emit.py), written on scheduled (non-dry) runs.

Last updated: 2026-07-05
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from zoneinfo import ZoneInfo

import config
from data import sources, dedup, macro_cal, earnings_cal, price_data
from classify import pipeline
from classify.llm_client import LLMClient
from score import aggregate
from store import db
from report import builder, telegram


def _now_utc() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


def run_scheduled(tier: config.TierSpec, secrets, dry_run: bool) -> int:
    db.init_db()
    con = db.connect()
    try:
        now = _now_utc()
        cutoff = db.last_report_cutoff(con, config.LOOKBACK_HOURS)
        lookback_h = max(config.LOOKBACK_HOURS,
                         int((now - cutoff).total_seconds() // 3600) + 1)
        lookback_h = min(lookback_h, 96)  # sanity cap
        print(f"[main] tier={tier.name} cutoff={cutoff.isoformat()} "
              f"lookback={lookback_h}h dry_run={dry_run}")

        # 1-2. ingest + dedup
        articles = sources.fetch_all(secrets, tier, lookback_h)
        source_counts: dict[str, int] = {}
        for a in articles:
            source_counts[a.source] = source_counts.get(a.source, 0) + 1
        clusters = dedup.cluster_articles(articles)

        # 3. classify (cascade)
        client = LLMClient(secrets.anthropic_key)
        signals = pipeline.classify_clusters(
            [c.to_dict() for c in clusters], client, tier)
        print(f"[main] {len(signals)} signals from {len(clusters)} clusters")
        if signals and not dry_run:
            db.insert_signals(con, signals, tier.name, now)

        # report timestamp in ET drives macro window-splitting
        report_dt_et = now.astimezone(ZoneInfo(config.REPORT_TZ))

        # 4. macro (separate tier, no LLM) — with pre-open/post-open windows
        macro_events = macro_cal.fetch_macro(
            secrets.finnhub_key, report_dt_et.date(), report_et=report_dt_et)
        if not macro_events:
            # Structured source empty (e.g. Finnhub's calendar/economic is
            # gated behind a paid plan) -> web-search-grounded fallback.
            # See config.py "6b. MACRO CALENDAR" for cost/design rationale.
            macro_events = macro_cal.fetch_macro_web(
                client, config.MACRO_WEB_MODEL, report_dt_et.date(),
                report_et=report_dt_et)
        if macro_events and not dry_run:
            db.insert_macro(con, macro_events, now)

        # 4b. earnings this week for watched names (all tiers; no LLM)
        earnings_events = earnings_cal.fetch_earnings(
            secrets.finnhub_key, report_dt_et.date())
        if earnings_events and not dry_run:
            db.insert_earnings(con, earnings_events, now)

        # 5. aggregate over everything since cutoff
        if dry_run:
            # aggregate just this run's freshly-built signals
            records = [{
                "ticker": s.ticker, "sentiment": s.sentiment,
                "magnitude": s.magnitude, "weight": s.weight,
                "event_type": s.event_type, "is_spillover": s.is_spillover,
                "created_utc": now, "one_line": s.one_line,
            } for s in signals]
        else:
            records = db.signals_since(con, cutoff)

        baseline = db.trailing_baseline(con) if tier.surprise_term else {}
        composites = aggregate.compute_composites(records, now, tier, baseline)

        # 5b. [premium/platinum] signal validation — resolve entries whose
        # horizon elapsed, then record this run's composites as new pending
        # validations. Backend-only: uses Yahoo's UNOFFICIAL chart endpoint
        # (see data/price_data.py) purely to compute the trailing hit-rate;
        # never surfaced to a customer directly.
        if tier.validation and not dry_run:
            _run_validation_cycle(con, composites, now)

        # 6. build + deliver
        validation_stats = _validation_stats(con) if tier.validation else None
        text, bluf = builder.build_report(
            composites, macro_events, earnings_events, tier, report_dt_et,
            validation_stats=validation_stats, source_counts=source_counts)

        # tier feature: machine-readable output for the options suite
        if tier.json_output:
            _write_json(bluf, macro_events, earnings_events, tier, report_dt_et, dry_run)

        # day_trader_pro: full-slate report.json for morning selection
        if not dry_run:
            from report import emit
            emit.emit_report(composites, macro_events, earnings_events, report_dt_et)

        sent = telegram.send(text, secrets)

        # 7. record
        if not dry_run:
            report_date = report_dt_et.strftime("%Y-%m-%d")
            db.insert_composites(con, composites, report_date, tier.name, now)
            if sent:
                db.record_report(con, report_date, tier.name, cutoff, now, bluf)
        return 0
    finally:
        con.close()


def _write_json(bluf, macro_events, earnings_events, tier, report_dt_et, dry_run: bool) -> None:
    payload = {
        "generated_utc": _now_utc().isoformat(),
        "report_date_et": report_dt_et.strftime("%Y-%m-%d"),
        "tier": tier.name,
        "bluf": bluf,
        "macro": [{
            "label": e.label, "type": e.event_type, "magnitude": e.magnitude,
            "release_et": e.release_et.isoformat(), "window": e.window,
            "actual": e.actual, "forecast": e.forecast,
        } for e in macro_events],
        "earnings_this_week": [{
            "symbol": e.symbol, "date": e.date.isoformat(),
            "session": e.session, "eps_estimate": e.eps_estimate,
        } for e in earnings_events],
    }
    out_dir = os.path.join(os.path.dirname(config.DB_PATH), "out")
    os.makedirs(out_dir, exist_ok=True)
    path = os.path.join(out_dir, "latest_signal.json")
    if dry_run:
        print(f"[main] (dry-run) JSON that would be written to {path}:")
        print(json.dumps(payload, indent=2))
        return
    with open(path, "w") as fh:
        json.dump(payload, fh, indent=2)
    print(f"[main] wrote suite-consumable JSON -> {path}")


def _run_validation_cycle(con, composites, now: dt.datetime) -> None:
    """[premium/platinum] Resolve validations whose horizon elapsed, then
    record this run's top composites as new pending validations. Uses
    Yahoo's unofficial chart endpoint (data/price_data.py) — best-effort,
    backend-only; failures here never block the report."""
    due = db.due_validations(con, now)
    if due:
        tickers = sorted({d["ticker"] for d in due})
        prices = price_data.fetch_prices(tickers)
        resolved = 0
        for d in due:
            cur = prices.get(d["ticker"])
            if cur is None or not d["price_at_signal"]:
                continue
            fwd_return = (cur - d["price_at_signal"]) / d["price_at_signal"]
            db.resolve_validation(con, d["id"], fwd_return)
            resolved += 1
        print(f"[main] validation: resolved {resolved}/{len(due)} due entries")

    if composites:
        top = composites[:config.VALIDATION_MAX_TICKERS]
        prices = price_data.fetch_prices([c.ticker for c in top])
        rows = [{"ticker": c.ticker, "signal_score": c.score,
                 "price_at_signal": prices[c.ticker],
                 "horizon_hours": config.VALIDATION_HORIZON_HOURS}
                for c in top if c.ticker in prices]
        if rows:
            db.insert_pending_validations(con, rows, now)
            print(f"[main] validation: recorded {len(rows)} new pending entries")


def _validation_stats(con) -> dict:
    row = con.execute(
        "SELECT COUNT(*) n, "
        "AVG(CASE WHEN signal_score*forward_return > 0 THEN 1.0 ELSE 0.0 END) hr "
        "FROM validation WHERE forward_return IS NOT NULL").fetchone()
    if row and row["n"]:
        return {"n": row["n"], "hit_rate": row["hr"]}
    return {"n": 0, "hit_rate": None}


def run_intraday(tier: config.TierSpec, secrets, dry_run: bool) -> int:
    """Premium: news shock scan. Platinum: also political/Truth-Social shocks."""
    if not tier.intraday_alerts:
        print("[main] intraday alerts require premium/platinum; nothing to do.")
        return 0
    db.init_db()
    con = db.connect()
    try:
        now = _now_utc()
        client = LLMClient(secrets.anthropic_key)

        # ---- news-based intraday shocks ---------------------------------
        articles = sources.fetch_all(secrets, tier, 2)  # last 2h
        clusters = dedup.cluster_articles(articles)
        signals = pipeline.classify_clusters(
            [c.to_dict() for c in clusters], client, tier)

        # persist ALL intraday signals so they feed the next morning rollup
        if signals and not dry_run:
            db.insert_signals(con, signals, tier.name, now)

        shocks = [s for s in signals
                  if not s.is_spillover
                  and abs(s.sentiment) * s.magnitude >= config.INTRADAY_SHOCK_FLOOR]

        # dedup: one ping per (ticker, cluster) event
        fresh = []
        for s in shocks:
            key = f"news:{s.ticker}:{s.cluster_id}"
            if db.already_alerted(con, key):
                continue
            fresh.append(s)
            if not dry_run:
                db.mark_alerted(con, key, "news_shock", now)

        if fresh:
            lines = ["*⚡ INTRADAY SHOCK ALERT*", ""]
            for s in fresh[:8]:
                arrow = "🟢▲" if s.sentiment > 0 else "🔴▼"
                lines.append(f"{arrow} *{s.ticker}* "
                             f"`{s.sentiment:+.2f}`×`{s.magnitude:.2f}` — {s.one_line}")
            telegram.send("\n".join(lines), secrets)
        else:
            print("[main] no new news shocks over threshold.")

        # ---- platinum: political / Truth-Social shocks ------------------
        if tier.political_feed:
            _run_political_scan(tier, secrets, client, con, now, dry_run)

        return 0
    finally:
        con.close()


def _run_political_scan(tier, secrets, client, con, now, dry_run: bool) -> None:
    """[platinum] Fetch Trump posts since last scan, classify, push shocks once."""
    from data import political
    from classify import political as pol_classify

    since = now - dt.timedelta(hours=2)
    posts = political.fetch_political_posts(since)
    if not posts:
        return

    alerts = []
    for p in posts:
        content_key = f"polhash:{hashlib.sha1(p.text.strip().lower().encode()).hexdigest()[:16]}"
        if db.already_alerted(con, f"pol:{p.id}") or db.already_alerted(con, content_key):
            continue
        res = pol_classify.classify_post(client, tier.deep_model, p.text)
        if not dry_run:
            db.mark_alerted(con, f"pol:{p.id}", "political", now)
            db.mark_alerted(con, content_key, "political_hash", now)
        if res["market_moving"] and res["magnitude"] >= config.POLITICAL_SHOCK_FLOOR:
            alerts.append((p, res))
            # persist as signals against affected tickers (feeds rollup)
            if res["tickers"] and not dry_run:
                _persist_political_signals(con, res, tier.name, now)

    if not alerts:
        print("[main] no political shocks over threshold.")
        return

    lines = ["*🏛️⚡ POLITICAL SHOCK — VOLATILITY WARNING*",
             "_A market-moving post just landed. Brace; don't be mid-trade._", ""]
    for p, res in alerts[:5]:
        arrow = "🟢▲" if res["sentiment"] > 0 else "🔴▼"
        scope = "BROAD MARKET" if res["broad"] else ", ".join(res["tickers"][:6]) or "market"
        lines.append(f"{arrow} *{scope}* (mag `{res['magnitude']:.2f}`) — {res['one_line']}")
        if p.url:
            lines.append(f"   {p.url}")
    telegram.send("\n".join(lines), secrets)


def _persist_political_signals(con, res, tier_name: str, now: dt.datetime) -> None:
    from classify.pipeline import Signal
    sigs = [Signal(
        ticker=t, sentiment=res["sentiment"], magnitude=res["magnitude"],
        weight=config.DIRECT_MENTION_WEIGHT, event_type="MACRO",
        scope="POLITICAL", is_spillover=False, model_used="political",
        confidence=0.6, cluster_id=None, one_line=res["one_line"], rationale="",
    ) for t in res["tickers"]]
    if sigs:
        db.insert_signals(con, sigs, tier_name, now)




def _build_sample(tier):
    """Synthetic but realistic data for --selftest and --preview (no network)."""
    from score.aggregate import compute_composites
    now = _now_utc()
    records = [
        {"ticker": "NVDA", "sentiment": 0.8, "magnitude": 0.9, "weight": 1.0,
         "event_type": "GUIDANCE", "is_spillover": False, "created_utc": now,
         "one_line": "raised datacenter guidance"},
        {"ticker": "AMD", "sentiment": 0.8, "magnitude": 0.9, "weight": 0.35,
         "event_type": "GUIDANCE", "is_spillover": True, "created_utc": now,
         "one_line": "semis spillover from NVDA"},
        {"ticker": "TSLA", "sentiment": -0.6, "magnitude": 0.7, "weight": 1.0,
         "event_type": "REGULATORY", "is_spillover": False,
         "created_utc": now - dt.timedelta(hours=12), "one_line": "recall probe"},
        {"ticker": "XOM", "sentiment": 0.45, "magnitude": 0.6, "weight": 1.0,
         "event_type": "GENERAL", "is_spillover": False, "created_utc": now,
         "one_line": "crude pops on supply headline"},
    ]
    comps = compute_composites(records, now, tier, {"NVDA": 0.2})
    et = ZoneInfo(config.REPORT_TZ)
    report_et = now.astimezone(et)
    day = report_et.date()
    macro_events = [
        macro_cal.MacroEvent(
            event_type="CORE_CPI", label="Core CPI (MoM)",
            release_et=dt.datetime.combine(day, dt.time(8, 30), tzinfo=et),
            magnitude=0.95, window=macro_cal.WINDOW_PRE_OPEN,
            actual="0.4%", forecast="0.3%"),
        macro_cal.MacroEvent(
            event_type="FOMC_RATE_DECISION", label="FOMC Rate Decision",
            release_et=dt.datetime.combine(day, dt.time(14, 0), tzinfo=et),
            magnitude=1.0, window=macro_cal.WINDOW_AFTERNOON, forecast="hold"),
    ]
    earnings_events = [
        earnings_cal.EarningsEvent(symbol="NVDA",
            date=day + dt.timedelta(days=1), session="amc", eps_estimate=1.12),
        earnings_cal.EarningsEvent(symbol="ORCL",
            date=day + dt.timedelta(days=2), session="bmo", eps_estimate=None),
    ]
    return comps, macro_events, earnings_events, report_et


def _sample_shock_text() -> str:
    """A sample intraday + political shock alert, for previewing that format."""
    return "\n".join([
        "*⚡ INTRADAY SHOCK ALERT*", "",
        "🔴▼ *TSLA* `-0.82`×`0.90` — NHTSA opens defect probe into 1.2M vehicles",
        "🟢▲ *NVDA* `+0.78`×`0.88` — cloud giant raises datacenter capex outlook",
        "", "———", "",
        "*🏛️⚡ POLITICAL SHOCK — VOLATILITY WARNING*",
        "_A market-moving post just landed. Brace; don't be mid-trade._", "",
        "🔴▼ *BROAD MARKET* (mag `0.90`) — 100% tariff threat on named trade partners",
        "🟢▲ *MU* (mag `0.72`) — praises Micron's $250M US investment by name",
    ])


def run_selftest() -> int:
    """Offline: exercise dedup + aggregate + report with no network/keys."""
    tier = config.TIERS["mid"]
    comps, macro_events, earnings_events, report_et = _build_sample(tier)
    text, bluf = builder.build_report(
        comps, macro_events, earnings_events, tier, report_et)
    print(text)
    print("\nBLUF JSON:", json.dumps(bluf, indent=2))
    assert comps[0].ticker == "NVDA", "expected NVDA to top the ranking"
    assert bluf[0]["earnings_this_week"] is not None, "NVDA earnings tag missing"
    assert macro_cal.is_fomc_day(macro_events), "FOMC day not detected"

    # platinum tier + political HTML-strip parse (offline, no network/LLM)
    from data import political
    assert "platinum" in config.TIERS and config.TIERS["platinum"].political_feed
    sample = ('Massive new TARIFFS on China effective immediately! '
              '<span class="h-card"><a href="x">@FoxNews</a></span> &amp; more')
    stripped = political._strip_html(sample)
    assert "<" not in stripped and "@FoxNews" in stripped and "&" in stripped
    assert political._parse_ts("2026-03-09T10:41:28.605Z") is not None
    print("[selftest] political parse + platinum tier OK")

    # price_data / validation round-trip (offline — Yahoo mocked, no network)
    import tempfile
    from unittest.mock import patch, MagicMock
    from data import price_data as _pd
    from store import db as _db

    assert _pd._yahoo_symbol("SPX") == "^GSPC", "SPX must map to ^GSPC for Yahoo"
    assert _pd._yahoo_symbol("AAPL") == "AAPL", "non-mapped tickers pass through unchanged"

    def _fake_get(url, params=None, headers=None, timeout=None):
        resp = MagicMock()
        resp.raise_for_status = lambda: None
        price = 500.0 if "%5EGSPC" in url or "^GSPC" in url else 200.0
        resp.json = lambda: {"chart": {"result": [{"meta": {"regularMarketPrice": price}}]}}
        return resp

    with tempfile.TemporaryDirectory() as tmp:
        old_db_path = config.DB_PATH
        config.DB_PATH = f"{tmp}/selftest.db"
        try:
            _db.init_db()
            con = _db.connect()
            now = _now_utc()
            past = now - dt.timedelta(hours=config.VALIDATION_HORIZON_HOURS + 1)
            with patch("data.price_data.requests.get", side_effect=_fake_get):
                # seed a pending validation as if it were created 25h ago at price 190
                _db.insert_pending_validations(
                    con, [{"ticker": "AAPL", "signal_score": 0.6,
                          "price_at_signal": 190.0, "horizon_hours": config.VALIDATION_HORIZON_HOURS}],
                    past)
                due = _db.due_validations(con, now)
                assert len(due) == 1, "25h-old entry with a 24h horizon must be due"
                prices = _pd.fetch_prices(["AAPL"])
                assert prices["AAPL"] == 200.0
                fwd = (prices["AAPL"] - due[0]["price_at_signal"]) / due[0]["price_at_signal"]
                _db.resolve_validation(con, due[0]["id"], fwd)
                row = con.execute("SELECT forward_return FROM validation WHERE id=?",
                                  (due[0]["id"],)).fetchone()
                assert abs(row["forward_return"] - (10.0 / 190.0)) < 1e-9
                assert _db.due_validations(con, now) == [], "resolved entry must no longer be due"
            con.close()
        finally:
            config.DB_PATH = old_db_path
    print("[selftest] price_data / validation round-trip OK")

    # macro web-search fallback: parsing + sanitization (mocked — no real
    # search/LLM call, since that would spend a real API key's money)
    from classify.llm_client import LLMClient as _LLMClient

    class _FakeClient:
        def web_search_json_call(self, **kwargs):
            return [
                {"event_type": "CORE_CPI", "label": "Core CPI (MoM)",
                 "release_time_et": "08:30", "actual": "0.3%",
                 "forecast": "0.3%", "previous": "0.2%"},
                {"event_type": "FOMC_RATE_DECISION", "label": "FOMC Rate Decision",
                 "release_time_et": "14:00", "actual": None, "forecast": "hold"},
                {"event_type": "NOT_A_REAL_TYPE", "label": "should be dropped",
                 "release_time_et": "10:00"},
                "not a dict — should also be skipped",
            ]

    fake_day = dt.date(2026, 7, 8)
    web_events = macro_cal.fetch_macro_web(_FakeClient(), "irrelevant-model", fake_day)
    assert len(web_events) == 2, "unknown event_type and non-dict rows must be dropped"
    cpi = next(e for e in web_events if e.event_type == "CORE_CPI")
    fomc = next(e for e in web_events if e.event_type == "FOMC_RATE_DECISION")
    assert cpi.window == macro_cal.WINDOW_PRE_OPEN, "08:30 with no report_et (default 09:15 ref) is pre-open"
    assert fomc.window == macro_cal.WINDOW_AFTERNOON, "14:00 must sort as afternoon"
    assert web_events[0].release_et < web_events[1].release_et, "must sort chronologically"
    assert cpi.actual == "0.3%"
    assert fomc.actual is None
    print("[selftest] macro web-search fallback parsing OK")

    print("\n[selftest] OK")
    return 0


def run_preview(secrets, tier: config.TierSpec) -> int:
    """Send a realistic SAMPLE rollup + shock alert to Telegram (bot token only).

    No news/LLM keys needed — uses synthetic data so you can judge the rendered
    look on your phone. Falls back to printing if no bot token is set.
    """
    comps, macro_events, earnings_events, report_et = _build_sample(tier)
    text, _ = builder.build_report(
        comps, macro_events, earnings_events, tier, report_et)
    banner = "*🧪 PREVIEW — sample data, not live*\n\n"
    print("[preview] sending sample rollup...")
    telegram.send(banner + text, secrets)
    print("[preview] sending sample shock alert...")
    telegram.send("*🧪 PREVIEW*\n\n" + _sample_shock_text(), secrets)
    print("[preview] done. Check Telegram (or above if no token set).")
    return 0


def run_testfeeds(secrets, tier: config.TierSpec) -> int:
    """Hit each configured data source and report counts. No send, no persist."""
    import datetime as _dt
    print(f"[testfeeds] tier={tier.name} sources={tier.sources}")
    arts = sources.fetch_all(secrets, tier, config.LOOKBACK_HOURS)
    by_src: dict[str, int] = {}
    for a in arts:
        by_src[a.source] = by_src.get(a.source, 0) + 1
    print(f"[testfeeds] news articles: {by_src or 'none'}")
    macro = macro_cal.fetch_macro(secrets.finnhub_key, _now_utc().date())
    print(f"[testfeeds] macro events (Finnhub): {len(macro)}")
    if not macro:
        print("[testfeeds] Finnhub macro empty -> testing web-search fallback "
             "(this makes a real, billable Anthropic call)...")
        client = LLMClient(secrets.anthropic_key)
        macro_web = macro_cal.fetch_macro_web(client, config.MACRO_WEB_MODEL)
        print(f"[testfeeds] macro events (web-search fallback): {len(macro_web)}")
        for e in macro_web[:6]:
            print(f"    - {e.label} ({e.event_type}) {e.et_clock} "
                 f"actual={e.actual} forecast={e.forecast}")
    earn = earnings_cal.fetch_earnings(secrets.finnhub_key)
    print(f"[testfeeds] earnings this week: {len(earn)}")
    if tier.political_feed:
        from data import political
        posts = political.fetch_political_posts(_now_utc() - _dt.timedelta(hours=6))
        print(f"[testfeeds] political posts (6h): {len(posts)}")
    if tier.validation:
        test_symbols = ["AAPL", "SPX"]   # SPX exercises the ^GSPC mapping
        prices = price_data.fetch_prices(test_symbols)
        print(f"[testfeeds] validation price check {test_symbols}: {prices or 'none resolved'}")
    print("[testfeeds] OK")
    return 0


def run_config(tier: config.TierSpec, secrets) -> int:
    """Print active tier, feature flags, universe, and which secrets are set."""
    def _mask(v: str) -> str:
        if not v:
            return "— NOT SET"
        return f"set ({len(v)} chars, …{v[-4:]})" if len(v) > 4 else "set"
    print(f"Active tier      : {tier.name}")
    print(f"  deep model     : {tier.deep_model or '—'}")
    print(f"  triage model   : {tier.triage_model}")
    print(f"  surprise term  : {tier.surprise_term}")
    print(f"  llm spillover  : {tier.llm_spillover}")
    print(f"  sources        : {', '.join(tier.sources)}")
    print(f"  json output    : {tier.json_output}")
    print(f"  intraday alerts: {tier.intraday_alerts}")
    print(f"  validation     : {tier.validation}")
    print(f"  political feed : {tier.political_feed}")
    print(f"Universe ({len(config.UNIVERSE)}): {', '.join(config.UNIVERSE)}")
    print(f"DB path          : {config.DB_PATH}")
    print("Secrets:")
    print(f"  ANTHROPIC_API_KEY   : {_mask(secrets.anthropic_key)}")
    print(f"  FINNHUB_API_KEY     : {_mask(secrets.finnhub_key)}")
    print(f"  ALPHAVANTAGE_API_KEY: {_mask(secrets.alphavantage_key)}")
    print(f"  BENZINGA_API_KEY    : {_mask(secrets.benzinga_key)}")
    print(f"  TELEGRAM_BOT_TOKEN  : {_mask(secrets.telegram_token)}")
    print(f"  TELEGRAM_CHAT_ID    : {secrets.telegram_chat_id or '— NOT SET'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Vertigo Pre-market Brief")
    p.add_argument("--tier", choices=list(config.TIERS), help="override SCREENER_TIER")
    p.add_argument("--dry-run", action="store_true", help="print, don't send/record")
    p.add_argument("--intraday", action="store_true", help="premium shock scan")
    p.add_argument("--selftest", action="store_true", help="offline smoke test")
    p.add_argument("--preview", action="store_true",
                   help="send a SAMPLE rollup+shock to Telegram (bot token only)")
    p.add_argument("--testfeeds", action="store_true",
                   help="hit each data source, print counts, no send/persist")
    p.add_argument("--config", action="store_true",
                   help="print active tier, flags, and which secrets are set")
    args = p.parse_args(argv)

    # Auto-load .env for manual runs (systemd EnvironmentFile still wins).
    loaded = config.load_env_file()
    if loaded and (args.config or args.testfeeds):
        print(f"[env] loaded {loaded}")

    if args.selftest:
        return run_selftest()

    if args.tier:
        os.environ["SCREENER_TIER"] = args.tier
    if args.dry_run:
        config.DRY_RUN = True

    tier = config.active_tier()
    secrets = config.load_secrets()

    if args.config:
        return run_config(tier, secrets)
    if args.preview:
        return run_preview(secrets, tier)
    if args.testfeeds:
        return run_testfeeds(secrets, tier)
    if args.intraday:
        return run_intraday(tier, secrets, args.dry_run)
    return run_scheduled(tier, secrets, args.dry_run)


if __name__ == "__main__":
    sys.exit(main())
