#!/usr/bin/env bash
# =============================================================================
# install.sh — market_brief_v1 web installer  (market_brief_v1.3.0)
# Vertigo Capital — AI market-intelligence brief for day traders
#
# Curl-to-shell install (download then run so tmux + prompts work):
#   curl -fsSL https://raw.githubusercontent.com/TX-9AI/market_brief_v1/main/install.sh -o install.sh && bash install.sh
#
# Unattended: export the keys first (see bootstrap.example.sh) and this script
# skips every prompt. Single-file by design — no install.sh->setup.sh subprocess
# (that pattern breaks venv activation). Ends by dropping you INTO the venv at
# the working directory.
# =============================================================================
set -e
export DEBIAN_FRONTEND=noninteractive
export TERM=xterm-256color

REPO="${GITHUB_REPO:-TX-9AI/market_brief_v1}"
REPO="${REPO#https://}"; REPO="${REPO#http://}"; REPO="${REPO#github.com/}"
REPO="${REPO%.git}"; REPO="${REPO%/}"
INSTALL_DIR="$HOME/market-brief"
DEPLOY_DIR="$HOME/market-brief-deploy"
SERVICE_NAME="market-brief"
VENV="$INSTALL_DIR/venv"
VERSION="1.3.0"

GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; RED='\033[0;31m'
BOLD='\033[1m'; RESET='\033[0m'
step() { echo -e "\n${BOLD}${GREEN}[ $1 ]${RESET} $2"; }
ok()   { echo -e "  ${GREEN}✓${RESET}  $1"; }
info() { echo -e "  ${CYAN}→${RESET}  $1"; }
warn() { echo -e "  ${YELLOW}⚠${RESET}  $1"; }

# ── Run inside tmux so a dropped SSH session can't kill the install ──────────
if [ -z "$TMUX" ]; then
    command -v tmux >/dev/null 2>&1 || { sudo apt-get update -qq; sudo apt-get install -y -qq tmux; }
    if command -v tmux >/dev/null 2>&1 && [ -r "$0" ]; then
        exec tmux new-session -A -s deploy "bash '$(readlink -f "$0")'"
    else
        warn "tmux unavailable or piped input — running directly; keep this session connected."
    fi
fi

# ── Unattended detection ────────────────────────────────────────────────────
UNATTENDED=false
if [ -n "$ANTHROPIC_API_KEY" ] && [ -n "$FINNHUB_API_KEY" ] \
   && [ -n "$ALPHAVANTAGE_API_KEY" ] && [ -n "$TELEGRAM_BOT_TOKEN" ]; then
    UNATTENDED=true
fi
[ "$UNATTENDED" = true ] || exec < /dev/tty   # reconnect stdin for prompts

echo ""
echo -e "${BOLD}${CYAN}╔══════════════════════════════════════════════════════╗${RESET}"
echo -e "${BOLD}${CYAN}║   market_brief v${VERSION}   |   Vertigo Capital        ║${RESET}"
echo -e "${BOLD}${CYAN}║   AI market brief · 09:15 ET Telegram rollup         ║${RESET}"
echo -e "${BOLD}${CYAN}╚══════════════════════════════════════════════════════╝${RESET}"
[ "$UNATTENDED" = true ] && ok "Keys found in environment — unattended install."
echo ""

ask()        { local __n="$2"; local __cur="${!__n}"; [ -n "$__cur" ] || read -rp "    $1: " "$__n"; }
ask_secret() { local __n="$2"; local __cur="${!__n}"; [ -n "$__cur" ] || { read -rsp "    $1 (paste, ENTER): " "$__n"; echo ""; }; }

# ── STEP 1: config / tier ───────────────────────────────────────────────────
step "1/6" "Tier & credentials"
SCREENER_TIER="${SCREENER_TIER:-}"
if [ -z "$SCREENER_TIER" ]; then
    if [ "$UNATTENDED" = true ]; then SCREENER_TIER="free"; else
        echo "    Tiers: free | mid | premium | platinum"
        read -rp "    SCREENER_TIER [free]: " SCREENER_TIER
        SCREENER_TIER="${SCREENER_TIER:-free}"
    fi
fi
ask_secret "ANTHROPIC_API_KEY (required)" ANTHROPIC_API_KEY
ask_secret "FINNHUB_API_KEY (required)" FINNHUB_API_KEY
ask_secret "ALPHAVANTAGE_API_KEY (required)" ALPHAVANTAGE_API_KEY
ask_secret "TELEGRAM_BOT_TOKEN (required)" TELEGRAM_BOT_TOKEN
TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-}"
[ -n "$TELEGRAM_CHAT_ID" ] || { [ "$UNATTENDED" = true ] && TELEGRAM_CHAT_ID="6075312586" || { read -rp "    TELEGRAM_CHAT_ID [6075312586]: " TELEGRAM_CHAT_ID; TELEGRAM_CHAT_ID="${TELEGRAM_CHAT_ID:-6075312586}"; }; }
# optional — premium/platinum only
BENZINGA_API_KEY="${BENZINGA_API_KEY:-}"
GITHUB_TOKEN="${GITHUB_TOKEN:-}"
ok "Tier: ${SCREENER_TIER}"

# ── STEP 2: system packages ─────────────────────────────────────────────────
step "2/6" "System packages"
sudo apt-get update -qq
sudo apt-get install -y -qq python3 python3-pip python3-venv python-is-python3 git rsync sqlite3 curl
ok "Packages ready."

# ── STEP 3: fetch code ──────────────────────────────────────────────────────
step "3/6" "Fetching application"
if [ -f "./main.py" ] && [ -d "./classify" ]; then
    info "Local source detected — installing from current directory."
    SRC="$(pwd)"
else
    rm -rf "$DEPLOY_DIR"
    if [ -n "$GITHUB_TOKEN" ]; then
        CLONE_URL="https://${GITHUB_TOKEN}@github.com/${REPO}.git"   # private repo
        info "Cloning with token (private repo)."
    else
        CLONE_URL="https://github.com/${REPO}.git"                    # public repo
    fi
    git clone --depth 1 "$CLONE_URL" "$DEPLOY_DIR" -q
    SRC="$DEPLOY_DIR"
    ok "Cloned ${REPO}"
fi
mkdir -p "$INSTALL_DIR"
rsync -a --exclude='.git' --exclude='venv' --exclude='.env' \
    --exclude='*.db' --exclude='*.db-wal' --exclude='*.db-shm' \
    --exclude='__pycache__' --exclude='bootstrap.sh' --exclude='out' \
    "$SRC"/ "$INSTALL_DIR"/
chmod +x "$INSTALL_DIR"/*.sh 2>/dev/null || true
for f in main.py config.py requirements.txt; do
    [ -f "$INSTALL_DIR/$f" ] || { echo -e "${RED}ERROR: $f missing. Aborting.${RESET}"; exit 1; }
done
ok "Installed to ${INSTALL_DIR}"

# ── STEP 4: python env + deps ───────────────────────────────────────────────
step "4/6" "Python environment"
python3 -m venv "$VENV"
# shellcheck disable=SC1091
source "$VENV/bin/activate"
pip install --upgrade pip -q
pip install -r "$INSTALL_DIR/requirements.txt" -q   # anthropic + requests
deactivate
ok "Dependencies installed (anthropic, requests)."

# ── STEP 5: .env + systemd timer ────────────────────────────────────────────
step "5/6" ".env + systemd timer (09:15 ET, Mon–Fri)"
ENV_FILE="$INSTALL_DIR/.env"
cat > "$ENV_FILE" << ENVEOF
SCREENER_TIER=${SCREENER_TIER}
ANTHROPIC_API_KEY=${ANTHROPIC_API_KEY}
FINNHUB_API_KEY=${FINNHUB_API_KEY}
ALPHAVANTAGE_API_KEY=${ALPHAVANTAGE_API_KEY}
BENZINGA_API_KEY=${BENZINGA_API_KEY}
TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN}
TELEGRAM_CHAT_ID=${TELEGRAM_CHAT_ID}
POLITICAL_ARCHIVE_URL=https://ix.cnn.io/data/truth-social/truth_archive.json
POLITICAL_PUSH_ENDPOINT=
SCREENER_DB=${INSTALL_DIR}/screener.db
SCREENER_DRY_RUN=0
ENVEOF
chmod 600 "$ENV_FILE"
ok ".env written (chmod 600)."

VENV_PY="${VENV}/bin/python"
sudo tee /etc/systemd/system/${SERVICE_NAME}.service >/dev/null << UNIT
[Unit]
Description=market_brief v${VERSION} scheduled rollup — Vertigo Capital
After=network-online.target
Wants=network-online.target
[Service]
Type=oneshot
User=${USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_PY} ${INSTALL_DIR}/main.py
StandardOutput=append:${INSTALL_DIR}/screener.log
StandardError=append:${INSTALL_DIR}/screener.log
UNIT

sudo tee /etc/systemd/system/${SERVICE_NAME}.timer >/dev/null << 'UNIT'
[Unit]
Description=Run market_brief weekdays 09:15 ET
[Timer]
OnCalendar=Mon..Fri *-*-* 09:15:00 America/New_York
Persistent=true
[Install]
WantedBy=timers.target
UNIT

# intraday shock scan (premium/platinum) — installed, NOT auto-enabled
sudo tee /etc/systemd/system/${SERVICE_NAME}-intraday.service >/dev/null << UNIT
[Unit]
Description=market_brief intraday shock scan (premium/platinum)
After=network-online.target
[Service]
Type=oneshot
User=${USER}
WorkingDirectory=${INSTALL_DIR}
EnvironmentFile=${ENV_FILE}
ExecStart=${VENV_PY} ${INSTALL_DIR}/main.py --intraday
StandardOutput=append:${INSTALL_DIR}/screener.log
StandardError=append:${INSTALL_DIR}/screener.log
UNIT
sudo tee /etc/systemd/system/${SERVICE_NAME}-intraday.timer >/dev/null << 'UNIT'
[Unit]
Description=Intraday shock scan every 30m during US session
[Timer]
OnCalendar=Mon..Fri *-*-* 09:45..15:45/0:30:00 America/New_York
Persistent=false
[Install]
WantedBy=timers.target
UNIT

sudo systemctl daemon-reload
sudo systemctl enable --now ${SERVICE_NAME}.timer
ok "Scheduled timer enabled."
[ "$SCREENER_TIER" = "premium" ] || [ "$SCREENER_TIER" = "platinum" ] && \
    info "Enable intraday: sudo systemctl enable --now ${SERVICE_NAME}-intraday.timer"

# ── STEP 6: git + shell integration ─────────────────────────────────────────
step "6/6" "Repo + shell integration"
cd "$INSTALL_DIR"
if [ ! -d ".git" ]; then
    git init -q; git branch -M main 2>/dev/null || true
    git remote add origin "https://github.com/${REPO}.git" 2>/dev/null || true
    GH_OWNER="${REPO%%/*}"
    git config user.name "$GH_OWNER"
    git config user.email "${GH_OWNER}@users.noreply.github.com"
fi
[ -n "$GITHUB_TOKEN" ] && { echo "$GITHUB_TOKEN" > "$INSTALL_DIR/.gh_token"; chmod 600 "$INSTALL_DIR/.gh_token"; }
grep -q "market-brief/venv" ~/.bashrc || echo "source $VENV/bin/activate" >> ~/.bashrc
grep -q "cd $INSTALL_DIR" ~/.bashrc || echo "cd $INSTALL_DIR" >> ~/.bashrc
ok "push.sh ready; shell will open in the venv at ${INSTALL_DIR}."

# ── offline smoke test ──────────────────────────────────────────────────────
info "Running offline self-test..."
"$VENV_PY" main.py --selftest >/dev/null 2>&1 && ok "Self-test passed." || warn "Self-test issue — check manually."

# ── cleanup (shred any secrets bootstrap) ───────────────────────────────────
rm -rf "$DEPLOY_DIR"; rm -f "$HOME/install.sh"
for s in "$HOME/bootstrap.sh" "$HOME/cred.txt"; do
    [ -f "$s" ] && { command -v shred >/dev/null 2>&1 && shred -u "$s" 2>/dev/null || rm -f "$s"; }
done

echo ""
echo -e "${BOLD}${GREEN}✅  market_brief installed and scheduled (09:15 ET).${RESET}"
echo -e "  Tier: ${SCREENER_TIER}    Dir: ${INSTALL_DIR}"
echo -e "  Try:  ${BOLD}python main.py --preview${RESET}   (sends a sample brief to Telegram)"
echo -e "        ${BOLD}bash devtools.sh${RESET}            (debug / config menu)"
echo -e "        ${BOLD}systemctl list-timers ${SERVICE_NAME}.timer${RESET}"
echo ""

export PATH="$VENV/bin:$PATH"
cd "$INSTALL_DIR"
exec bash
