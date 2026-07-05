#!/usr/bin/env bash
# market_brief/push.sh — market_brief_v1.1.0
# Convention wrapper: use this instead of raw `git push`.
# Enforces LF on shell scripts, then commits + pushes. Works for PUBLIC or
# PRIVATE repos: if a token is available (env GITHUB_TOKEN or ./.gh_token) it
# pushes over an ephemeral tokened URL WITHOUT writing the token into
# .git/config.
#
# Usage: ./push.sh "commit message"
set -euo pipefail

MSG="${1:-update}"

# enforce LF + exec bit on shell scripts before committing
find . -name "*.sh" -not -path "./venv/*" -exec sed -i 's/\r$//' {} \;
find . -name "*.sh" -not -path "./venv/*" -exec chmod +x {} \;

git add -A
git commit -m "${MSG}" || echo "nothing to commit"

BRANCH="$(git rev-parse --abbrev-ref HEAD)"
TOKEN="${GITHUB_TOKEN:-}"
[ -z "$TOKEN" ] && [ -f .gh_token ] && TOKEN="$(tr -d '[:space:]' < .gh_token)"

REMOTE="$(git config --get remote.origin.url || true)"
REPO_PATH="${REMOTE#https://github.com/}"
REPO_PATH="${REPO_PATH#*@github.com/}"   # strip any user@ / token@ prefix
REPO_PATH="${REPO_PATH%.git}"

if [ -n "$TOKEN" ] && [ -n "$REPO_PATH" ]; then
    # ephemeral tokened URL — not persisted to .git/config
    git push "https://${TOKEN}@github.com/${REPO_PATH}.git" "$BRANCH"
else
    git push origin "$BRANCH"
fi
echo "pushed ${REPO_PATH:-origin} (${BRANCH})."
