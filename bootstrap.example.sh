#!/usr/bin/env bash
# =============================================================================
# bootstrap.example.sh — one-shot unattended deploy for market_brief_v1
#
# THIS FILE IS A TEMPLATE — PLACEHOLDERS ONLY. Safe to commit.
# Do NOT put real secrets here. Instead:
#   1. cp bootstrap.example.sh bootstrap.sh     # your copy — GITIGNORED
#   2. fill in the REPLACE_ME values in bootstrap.sh
#   3. scp bootstrap.sh ubuntu@YOUR_IP:~
#   4. on the box:  bash bootstrap.sh
#
# The installer runs in tmux (reconnect with `tmux attach -t deploy` if SSH
# drops), installs everything hands-free, and SHREDS bootstrap.sh during
# cleanup once the keys are written to .env. The .gitignore ignores every
# bootstrap*.sh EXCEPT this .example, so your real keys can never be committed.
# =============================================================================

# ── Tier: free | mid | premium | platinum ───────────────────────────────────
export SCREENER_TIER="free"

# ── Required on every tier ───────────────────────────────────────────────────
export ANTHROPIC_API_KEY="REPLACE_ME"
export FINNHUB_API_KEY="REPLACE_ME"
export ALPHAVANTAGE_API_KEY="REPLACE_ME"
export TELEGRAM_BOT_TOKEN="REPLACE_ME"
export TELEGRAM_CHAT_ID="6075312586"

# ── Optional (premium / platinum) ────────────────────────────────────────────
export BENZINGA_API_KEY=""            # premium/platinum news source
# Platinum political feed override (leave default unless you have a push feed):
# export POLITICAL_PUSH_ENDPOINT=""

# ── Optional: link this box to the repo for push.sh ──────────────────────────
export GITHUB_REPO="TX-9AI/market_brief_v1"
export GITHUB_TOKEN=""                # only needed to PUSH from this box

# ── Run the standard installer (inherits every export above) ─────────────────
# For a PRIVATE repo, the raw install.sh also needs the token; we add the auth
# header only when GITHUB_TOKEN is set (public repos work without it).
CURL_AUTH=()
[ -n "$GITHUB_TOKEN" ] && CURL_AUTH=(-H "Authorization: token ${GITHUB_TOKEN}")
curl -fsSL "${CURL_AUTH[@]}" \
    "https://raw.githubusercontent.com/${GITHUB_REPO}/main/install.sh" -o install.sh \
    && bash install.sh
