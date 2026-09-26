# market_brief/report/information.py — market_brief_v1.7.0
"""
THE INFORMATION BRIEF — facts, in a fixed order, with no opinion attached.

v1.0.0 — 2026-09-26 — the information-only collapse.

OPERATOR, 2026-09-25: *"It should come out at the same time every day and cover
the symbols that we trade, including the two new ones. And have that be
Information only. No LLM's. Or discretionary decisions—just a brief and that's
it. The reason for this is the market brief never actually correlated with the
days Trading — it was Information, but there was no edge to be gained and no
morning bias ended up correlating."*

WHAT THIS FILE REPLACES, AND WHY IT IS A DELETION RATHER THAN A REWRITE.
`builder.build_report` opened with *"BOTTOM LINE — LOOK HERE FIRST"*: four or
five tickers ranked by an LLM-built composite, each with a signed arrow and a
two-decimal number. otv4 C.46 (r382, 2026-09-14) had already ruled that out —
*"a briefing assigning scores that are not reliable indicators of what they
represent is almost worse than no scores"* — and the ruling was applied to the
BOTS and never to the READER it names first. This file is the reader's half,
eleven days late.

🔑 THE RULING WAS MADE ON EVIDENCE, AND THE EVIDENCE IS WHY NOTHING HERE
RANKS. Checked against the tape: 08-25's top five went 1 of 5 with both
above-floor calls wrong (MU called SHORT at conviction 0.74 while already
gapping +2.08% and closing +2.49%); 08-31 put five below-floor calls under the
bottom line; 09-10 — the strongest board in the sample — went 0 of 5, with MU
-4.62% on a -3.02% gap that was already printing before the brief went out.

SECTION ORDER IS FIXED AND CHRONOLOGICAL OR ALPHABETICAL, NEVER BY INTEREST.
Ordering is the last place an opinion hides: a list sorted by "most headlines"
or "biggest impact" is a ranking whether or not a number is printed beside it.
Macro is in clock order. Everything per-symbol is A-Z.

⚠️ MAGNITUDE IS DELIBERATELY NOT SHOWN. The old builder tagged each macro
release with an impact tier. A tier is a judgement about what matters today,
which is the thing the operator asked to remove; the release and its clock time
are the fact. If a consumer wants to weight CPI over jobless claims it can do
that from the event type, which is in the JSON.

🔴 AN ABSENT SOURCE IS NAMED. v1.1.1 printed "None scheduled / calendar
unavailable" — ONE STRING FOR TWO FACTS. A quiet calendar and a calendar that
did not answer are different mornings, and a brief that cannot tell them apart
is not information. Every section renders EMPTY and UNAVAILABLE differently,
and `availability` carries the same distinction into the JSON.
"""

from __future__ import annotations

import datetime as dt
from typing import Any

import config

_HEADLINES_SHOWN = 2      # titles per symbol; the count carries the rest

_SESS_SHORT = {"bmo": "BMO", "amc": "AMC", "dmh": "DMH", "unknown": "TBD"}

# One line per source, so a dark feed is visible in the brief itself rather
# than only in a log nobody opens on a weekday morning.
_LABEL = {"macro": "Macro calendar", "earnings": "Earnings calendar",
          "news": "News feeds", "prices": "Price feed"}


def _unavailable(section: str, reason: str = "") -> str:
    why = f" ({reason})" if reason else ""
    return (f"⚠️ {_LABEL.get(section, section)} UNAVAILABLE{why} — the source "
            f"did not answer. This is NOT the same as nothing being scheduled.")


def _headlines_by_symbol(headlines: list, universe: list[str]) -> dict[str, list]:
    """Group feed-attributed headlines A-Z. NOTHING here infers a ticker: the
    attribution rides on the feed's own per-company endpoint (`tickers_hint`),
    which is why this survives the model's removal intact."""
    uni = set(universe)
    out: dict[str, list] = {}
    for h in headlines or []:
        hints = getattr(h, "tickers_hint", None) or []
        if not hints and getattr(h, "ticker", None):
            hints = [h.ticker]
        for sym in hints:
            if sym in uni:
                out.setdefault(sym, []).append(h)
    return out


def build_information_brief(
    macro_events: list,
    earnings_events: list,
    headlines: list,
    prices: dict[str, float],
    report_dt_et: dt.datetime,
    availability: dict[str, bool] | None = None,
    universe: list[str] | None = None,
    reasons: dict[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Returns (markdown, payload). Pure — no network, no model, no state."""
    avail = {"macro": True, "earnings": True, "news": True, "prices": True}
    avail.update(availability or {})
    why = dict(reasons or {})
    uni = list(universe if universe is not None else config.UNIVERSE)
    today = report_dt_et.date()

    L: list[str] = []
    L.append(f"*VERTIGO CAPITAL MORNING BRIEF* — "
             f"{report_dt_et.strftime('%a %b %d, %Y')}")
    L.append(f"_{report_dt_et.strftime('%-I:%M %p ET').lower()} · information "
             f"only · {len(uni)} traded symbols_")
    L.append("")

    # ── MACRO, IN CLOCK ORDER ───────────────────────────────────────────
    L.append("*MACRO TODAY*")
    if not avail["macro"]:
        L.append(_unavailable("macro", why.get("macro", "")))
    elif not macro_events:
        L.append("• Nothing on the calendar today.")
    else:
        ordered = sorted(macro_events, key=lambda m: getattr(
            m, "release_et", report_dt_et))
        out, ahead = [], []
        for m in ordered:
            rel = getattr(m, "release_et", None)
            clock = getattr(m, "et_clock", "") or ""
            note = m.surprise_note() if hasattr(m, "surprise_note") else ""
            line = f"  • *{getattr(m, 'label', '?')}* — {clock}"
            if note and note != "scheduled":
                line += f"  ({note})"
            (out if (rel and rel <= report_dt_et) else ahead).append(line)
        if out:
            L.append("_Already out:_")
            L.extend(out)
        if ahead:
            L.append("_Still ahead:_")
            L.extend(ahead)
    L.append("")

    # ── EARNINGS THIS WEEK, A-Z ─────────────────────────────────────────
    L.append("*EARNINGS THIS WEEK*")
    if not avail["earnings"]:
        L.append(_unavailable("earnings", why.get("earnings", "")))
    else:
        mine = sorted([e for e in (earnings_events or [])
                       if getattr(e, "symbol", None) in set(uni)],
                      key=lambda e: (e.symbol,))
        if not mine:
            L.append("• None among the traded symbols this week.")
        for e in mine:
            when = "today" if e.date == today else e.date.strftime("%a %b %-d")
            sess = _SESS_SHORT.get(getattr(e, "session", "unknown"), "TBD")
            L.append(f"• *{e.symbol}* — {when}, {sess}")
    L.append("")

    # ── HEADLINES, A-Z BY SYMBOL ────────────────────────────────────────
    L.append("*HEADLINES BY SYMBOL* (A-Z)")
    if not avail["news"]:
        L.append(_unavailable("news", why.get("news", "")))
    else:
        grouped = _headlines_by_symbol(headlines, uni)
        if not grouped:
            L.append("• No headlines matched a traded symbol.")
        for sym in sorted(grouped):
            items = grouped[sym]
            # TWO titles, and the COUNT carries the rest. The operator asked
            # for this to be de-emphasized; a brief that needs two Telegram
            # messages is not de-emphasized. The count is the fact ("NVDA had
            # 159 stories today"), the titles are the sample, and a third
            # title bought ~1.2k characters for no additional fact.
            L.append(f"*{sym}* ({len(items)})")
            for h in items[:_HEADLINES_SHOWN]:
                src = getattr(h, "source", "?")
                L.append(f"  – {getattr(h, 'title', '')}  _{src}_")
    L.append("")

    # ── LAST PRICE, A-Z ─────────────────────────────────────────────────
    L.append("*LAST PRICE*")
    if not avail["prices"]:
        L.append(_unavailable("prices", why.get("prices", "")))
    elif not prices:
        L.append("• No prices returned.")
    else:
        got = [f"{s} {prices[s]:,.2f}" for s in sorted(uni) if s in prices]
        L.append("  " + " · ".join(got) if got else "• No prices returned.")
        missing = [s for s in sorted(uni) if s not in prices]
        if missing:
            L.append(f"_No quote for: {', '.join(missing)}_")
    L.append("")

    # ── WHAT ANSWERED ───────────────────────────────────────────────────
    dark = [_LABEL[k] for k in sorted(avail) if not avail[k]]
    L.append("_Sources: " + ("all answered" if not dark
                             else "NO ANSWER from " + ", ".join(dark)) + "._")

    payload: dict[str, Any] = {
        "date": today.isoformat(),
        "generated_at_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "brief_kind": "information",
        "universe": sorted(uni),
        "availability": dict(avail),
        "unavailable_because": {k: v for k, v in why.items() if not avail.get(k, True)},
        "macro": [{"event_type": getattr(m, "event_type", None),
                   "label": getattr(m, "label", None),
                   "et_clock": getattr(m, "et_clock", None)}
                  for m in (macro_events or [])],
        "earnings": [{"symbol": e.symbol, "date": e.date.isoformat(),
                      "session": getattr(e, "session", "unknown")}
                     for e in (earnings_events or [])
                     if getattr(e, "symbol", None) in set(uni)],
        "headlines": {s: [{"title": getattr(h, "title", ""),
                           "source": getattr(h, "source", ""),
                           "url": getattr(h, "url", "")}
                          for h in v]
                      for s, v in _headlines_by_symbol(headlines, uni).items()},
        "prices": {s: prices[s] for s in sorted(uni) if s in (prices or {})},
        "notes": ("information only — no signal payload. otv4 C.46 (r382) and "
                  "the operator's 2026-09-25 ruling: the brief never correlated "
                  "with the day's trading, so it carries no direction, no "
                  "ordering by interest, and nothing a bot may read as a prior."),
    }
    return "\n".join(L), payload
