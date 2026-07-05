# market_brief/classify/llm_client.py — market_brief_v1.1.0
"""
Thin wrapper around the Anthropic Messages API.

Responsibilities (one only): send a prompt to a named model, return parsed
JSON. All cascade logic lives in pipeline.py; all prompt text lives in
triage.py / scope.py. This file just does the call + safe parse + retry.

Model IDs are passed in by the caller (from config.TierSpec) so the tier
switch fully controls which model runs.

Last updated: 2026-07-04
"""

from __future__ import annotations

import json
import re
import time
from typing import Any

try:
    import anthropic
except ImportError:  # surfaced clearly at startup by main.py
    anthropic = None


_JSON_FENCE = re.compile(r"```(?:json)?\s*|\s*```", re.IGNORECASE)


class LLMClient:
    def __init__(self, api_key: str, max_retries: int = 2):
        if anthropic is None:
            raise RuntimeError(
                "The 'anthropic' package is not installed. "
                "Run: pip install anthropic"
            )
        if not api_key:
            raise RuntimeError(
                "ANTHROPIC_API_KEY is not set. Every tier uses at least Haiku."
            )
        self._client = anthropic.Anthropic(api_key=api_key)
        self._max_retries = max_retries

    def json_call(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 1024,
    ) -> dict[str, Any] | list[Any] | None:
        """
        Call `model`, instruct JSON-only output, parse and return it.
        Returns None on unrecoverable failure (caller decides fallback).
        """
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                )
                text = "".join(
                    block.text for block in resp.content
                    if getattr(block, "type", None) == "text"
                )
                return self._parse_json(text)
            except Exception as exc:  # network / rate / parse
                last_err = exc
                if attempt < self._max_retries:
                    time.sleep(1.5 * (attempt + 1))
                continue
        print(f"[llm_client] {model} failed after retries: {last_err}")
        return None

    def web_search_json_call(
        self,
        model: str,
        system: str,
        user: str,
        max_tokens: int = 1500,
        max_uses: int = 4,
    ) -> dict[str, Any] | list[Any] | None:
        """Same contract as json_call, but grants the model a server-side
        web_search tool so the answer is grounded in current, real
        information instead of training-data knowledge. Costs $0.01/search
        on top of normal token costs — used only for factual lookups (e.g.
        the economic calendar) where same-day accuracy matters more than
        that marginal cost.
        """
        last_err: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                resp = self._client.messages.create(
                    model=model,
                    max_tokens=max_tokens,
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    tools=[{
                        "type": "web_search_20250305",
                        "name": "web_search",
                        "max_uses": max_uses,
                    }],
                )
                text = "".join(
                    block.text for block in resp.content
                    if getattr(block, "type", None) == "text"
                )
                return self._parse_json(text)
            except Exception as exc:
                last_err = exc
                if attempt < self._max_retries:
                    time.sleep(1.5 * (attempt + 1))
                continue
        print(f"[llm_client] {model} web-search call failed after retries: {last_err}")
        return None

    @staticmethod
    def _parse_json(text: str) -> Any:
        cleaned = _JSON_FENCE.sub("", text).strip()
        # tolerate a leading sentence before the JSON blob
        start = min(
            (i for i in (cleaned.find("{"), cleaned.find("[")) if i != -1),
            default=-1,
        )
        if start > 0:
            cleaned = cleaned[start:]
        return json.loads(cleaned)
