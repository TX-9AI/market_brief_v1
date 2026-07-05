#!/usr/bin/env bash
# =============================================================================
# devtools.sh — market_brief dev/debug console  (market_brief_v1.2.0)
# Basic debugging + configuration queries over the most-touched parts:
# config, data feeds, the SQLite store, Telegram delivery, and the timer.
#   Usage:  bash devtools.sh
# =============================================================================
set -uo pipefail
cd "$(dirname "$(readlink -f "$0")")"

VENV_PY="./venv/bin/python"
[ -x "$VENV_PY" ] || VENV_PY="python3"
SERVICE_NAME="market-brief"

# load .env so keys are available to python + sqlite path is known
if [ -f ".env" ]; then set -a; . ./.env; set +a; fi
DB="${SCREENER_DB:-./screener.db}"

BOLD='\033[1m'; GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RESET='\033[0m'
hdr() { echo -e "\n${BOLD}${CYAN}── $1 ──${RESET}"; }
pause() { echo ""; read -rp "  [enter] to return to menu..."; }

sql() {  # run a query if the DB exists
    if [ ! -f "$DB" ]; then echo "  (no DB yet at $DB — run a report first)"; return; fi
    sqlite3 -header -column "$DB" "$1"
}

menu() {
cat <<'MENU'

  ══ market_brief devtools ═════════════════════════════
   CONFIG & FEEDS
    1) Active tier, flags & which keys are set
    2) Test all data feeds (counts, no send)
    3) Send SAMPLE brief + shock to Telegram (preview)
    4) Telegram connectivity ping
   STORE (SQLite)
    5) Recent signals (last 20)
    6) Latest composites / last report BLUF
    7) Macro events (today)
    8) Earnings this week
    9) Shock-alert ledger (dedup table)
   10) Validation entries (pending + resolved, backtest results)
   11) Table row counts / DB health
   RUN
   12) Offline self-test
   13) Dry-run report (live data, prints, no send)
   14) Run intraday shock scan now
   15) Force a REAL scheduled report now (sends!)
   SERVICE
   16) Timer status + next run
   17) Tail service log (Ctrl-C to stop)
   18) Switch tier in .env
   19) Edit .env
   20) Stop service, clear cache & restart
    0) Quit
  ══════════════════════════════════════════════════════
MENU
}

while true; do
    menu
    read -rp "  choose: " c
    case "$c" in
        1) hdr "Config"; $VENV_PY main.py --config; pause;;
        2) hdr "Feed test"; $VENV_PY main.py --testfeeds; pause;;
        3) hdr "Preview send"; $VENV_PY main.py --preview; pause;;
        4) hdr "Telegram ping"
           if [ -z "${TELEGRAM_BOT_TOKEN:-}" ]; then echo "  TELEGRAM_BOT_TOKEN not set."; else
             curl -s "https://api.telegram.org/bot${TELEGRAM_BOT_TOKEN}/sendMessage" \
               -d chat_id="${TELEGRAM_CHAT_ID:-}" \
               -d text="✅ market_brief devtools ping $(date '+%H:%M:%S')" >/dev/null \
               && echo "  sent — check Telegram." || echo "  send failed."
           fi; pause;;
        5) hdr "Recent signals"; sql "SELECT substr(created_utc,1,16) t, ticker, round(sentiment,2) sent, round(magnitude,2) mag, event_type, scope, tier FROM signals ORDER BY id DESC LIMIT 20;"; pause;;
        6) hdr "Latest composites"; sql "SELECT report_date, ticker, round(score,3) score, direction, round(surprise_delta,3) surprise, tier FROM composites ORDER BY id DESC LIMIT 15;"
           hdr "Last report"; sql "SELECT report_date, tier, substr(sent_utc,1,16) sent FROM reports ORDER BY id DESC LIMIT 3;"; pause;;
        7) hdr "Macro today"; sql "SELECT label, round(magnitude,2) mag, substr(release_utc,1,16) release_utc, actual, forecast FROM macro_events WHERE substr(release_utc,1,10)=date('now') ORDER BY magnitude DESC;"; pause;;
        8) hdr "Earnings this week"; sql "SELECT symbol, earn_date, session, eps_estimate FROM earnings_events WHERE earn_date >= date('now') ORDER BY earn_date;"; pause;;
        9) hdr "Shock ledger"; sql "SELECT substr(created_utc,1,16) t, kind, substr(event_key,1,40) key FROM alerted_events ORDER BY id DESC LIMIT 20;"; pause;;
        10) hdr "Pending validations (forward return not yet resolved)"
            sql "SELECT id, substr(created_utc,1,16) t, ticker, round(signal_score,3) score, round(price_at_signal,2) entry_px, horizon_hours FROM validation WHERE forward_return IS NULL ORDER BY id DESC LIMIT 15;"
            hdr "Resolved validations (backtest results)"
            sql "SELECT id, substr(created_utc,1,16) t, ticker, round(signal_score,3) score, round(forward_return,4) fwd_ret, (signal_score*forward_return>0) hit FROM validation WHERE forward_return IS NOT NULL ORDER BY id DESC LIMIT 15;"
            hdr "Trailing hit-rate"
            sql "SELECT COUNT(*) n, ROUND(AVG(CASE WHEN signal_score*forward_return>0 THEN 1.0 ELSE 0.0 END),3) hit_rate FROM validation WHERE forward_return IS NOT NULL;"
            pause;;
        11) hdr "Row counts"
            for t in signals composites macro_events earnings_events reports validation alerted_events; do
                sql "SELECT '$t' AS tbl, COUNT(*) AS rows FROM $t;" 2>/dev/null
            done; pause;;
        12) hdr "Self-test"; $VENV_PY main.py --selftest; pause;;
        13) hdr "Dry run"; $VENV_PY main.py --dry-run; pause;;
        14) hdr "Intraday scan"; $VENV_PY main.py --intraday; pause;;
        15) read -rp "  This SENDS a real report. Type 'yes' to confirm: " y
            [ "$y" = "yes" ] && $VENV_PY main.py || echo "  cancelled."; pause;;
        16) hdr "Timer"; systemctl list-timers "${SERVICE_NAME}.timer" --no-pager 2>/dev/null || echo "  (systemd not available here)"; pause;;
        17) hdr "Log tail"; tail -n 40 -f screener.log 2>/dev/null || echo "  no screener.log yet";;
        18) read -rp "  new tier [free/mid/premium/platinum]: " nt
            case "$nt" in free|mid|premium|platinum)
                if grep -q '^SCREENER_TIER=' .env 2>/dev/null; then
                    sed -i "s/^SCREENER_TIER=.*/SCREENER_TIER=${nt}/" .env
                else echo "SCREENER_TIER=${nt}" >> .env; fi
                echo "  tier set to ${nt} (restart timer/service to apply).";;
                *) echo "  invalid tier.";; esac; pause;;
        19) "${EDITOR:-nano}" .env; pause;;
        20) hdr "Stop service, clear cache & restart"
            echo "  This will:"
            echo "    - stop the timer(s) + any in-flight run"
            echo "    - clear __pycache__/*.pyc and out/ (regenerable — NOT the database;"
            echo "      signals, composites, and the shock dedup ledger are preserved)"
            echo "    - restart the timer(s), re-enabling intraday only if it was already on"
            read -rp "  Proceed? [y/N]: " go
            if [ "$go" = "y" ] || [ "$go" = "Y" ]; then
                INTRADAY_ON=false
                systemctl is-enabled "${SERVICE_NAME}-intraday.timer" >/dev/null 2>&1 && INTRADAY_ON=true

                echo "  stopping..."
                sudo systemctl stop "${SERVICE_NAME}.timer" "${SERVICE_NAME}.service" 2>/dev/null
                sudo systemctl stop "${SERVICE_NAME}-intraday.timer" "${SERVICE_NAME}-intraday.service" 2>/dev/null

                echo "  clearing cache..."
                find . -name "__pycache__" -type d -not -path "./venv/*" -exec rm -rf {} + 2>/dev/null
                find . -name "*.pyc" -not -path "./venv/*" -delete 2>/dev/null
                rm -rf out
                echo "  (database untouched: $DB)"

                echo "  restarting..."
                sudo systemctl daemon-reload
                sudo systemctl start "${SERVICE_NAME}.timer"
                [ "$INTRADAY_ON" = true ] && sudo systemctl start "${SERVICE_NAME}-intraday.timer"

                echo "  done."
                systemctl list-timers "${SERVICE_NAME}.timer" "${SERVICE_NAME}-intraday.timer" --no-pager 2>/dev/null
            else
                echo "  cancelled."
            fi; pause;;
        0) echo "  bye."; exit 0;;
        *) echo "  ?";;
    esac
done
