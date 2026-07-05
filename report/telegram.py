# market_brief/report/telegram.py — market_brief_v1.0.0
"""
Telegram delivery.

One responsibility: push a (possibly long) markdown report to the configured
chat, chunked under Telegram's 4096-char limit. Honors config.DRY_RUN
(prints instead of sending) so you can dev on mobile without spamming.

Uses a dedicated bot token (env TELEGRAM_BOT_TOKEN) — per convention this
screener gets its OWN bot, reusing the existing chat id 6075312586.

Last updated: 2026-07-04
"""

from __future__ import annotations

import time

import requests

import config

_LIMIT = 4000  # leave headroom under 4096


def _chunk(text: str) -> list[str]:
    if len(text) <= _LIMIT:
        return [text]
    chunks, buf = [], []
    size = 0
    for line in text.split("\n"):
        if size + len(line) + 1 > _LIMIT and buf:
            chunks.append("\n".join(buf))
            buf, size = [], 0
        buf.append(line)
        size += len(line) + 1
    if buf:
        chunks.append("\n".join(buf))
    return chunks


def send(text: str, secrets) -> bool:
    if config.DRY_RUN:
        print("----- DRY RUN (SCREENER_DRY_RUN=1): report not sent -----")
        print(text)
        print("---------------------------------------------------------")
        return True

    if not secrets.telegram_token:
        print("[telegram] TELEGRAM_BOT_TOKEN missing -> printing instead:")
        print(text)
        return False

    url = f"https://api.telegram.org/bot{secrets.telegram_token}/sendMessage"
    ok = True
    for part in _chunk(text):
        try:
            r = requests.post(url, json={
                "chat_id": secrets.telegram_chat_id,
                "text": part,
                "parse_mode": "Markdown",
                "disable_web_page_preview": True,
            }, timeout=config.HTTP_TIMEOUT)
            if r.status_code != 200:
                print(f"[telegram] send failed {r.status_code}: {r.text[:200]}")
                ok = False
            time.sleep(0.4)  # gentle on rate limits across chunks
        except Exception as exc:
            print(f"[telegram] error: {exc}")
            ok = False
    return ok
