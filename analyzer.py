"""
analyzer.py — Market intelligence via local Ollama model.

Receives real market data (prices, technicals, options chain, live news)
and produces a single actionable trade recommendation with:
  - Direction + conviction
  - Entry, stop, targets
  - Timeframe breakdown (scalp / swing / position)
  - Specific options strategy based on real IV and strikes
"""

from __future__ import annotations

import json
import os
import re
from typing import Any

import ollama

MODEL = os.getenv("OLLAMA_MODEL", "llama3.2")

# ── System prompt ─────────────────────────────────────────────────────────────

_SYSTEM = """
You are a senior commodity strategist and derivatives trader with 30 years of experience.
You manage a multi-billion dollar energy book. You have deep expertise in:
- Crude oil futures (WTI, Brent) and physical markets
- Geopolitical risk pricing and speculative premium analysis
- Options structures (spreads, straddles, risk reversals) and volatility trading
- Technical analysis grounded in market structure

You will receive REAL market data: live prices, RSI, moving averages, MACD, volume,
options put/call ratios, ATM implied volatility, and live news headlines.

Your job: produce ONE actionable trade recommendation. No hedging. One view.

Rules:
1. Your price targets, entry, and stop must be based on the REAL prices provided.
2. Your options strategy must reference the REAL implied volatility and strikes provided.
3. If RSI > 70 note overbought risk. If RSI < 30 note oversold opportunity.
4. If IV is elevated (>35%), recommend spreads over naked options to reduce cost.
5. If IV is low (<20%), naked calls/puts are cheap — favour directional buys.
6. If MACD is bullish and price is above MA20, the technical setup is constructive.
7. The put/call ratio below 0.8 = market is positioned bullish; above 1.2 = bearish hedge.
8. Show the reasoning chain — don't just give targets, explain WHY those levels.

Return ONLY a valid JSON object matching this exact schema:

{
  "verdict":     "LONG or SHORT or HOLD",
  "conviction":  "HIGH or MEDIUM or LOW",
  "thesis":      "2-3 sentences. The core argument using the real data provided.",

  "entry_zone":  "price range to enter e.g. $71.50-$73.00",
  "stop":        "stop loss level e.g. $68.00 with rationale",
  "target_1":    "first target e.g. $82.00 (prior resistance)",
  "target_2":    "second target e.g. $90.00 (bull case)",
  "risk_reward": "e.g. 1:2.4 to T1",

  "timeframes": {
    "scalp": {
      "direction": "LONG or SHORT or SKIP",
      "play":  "specific entry and target for 1-3 day trade",
      "stop":  "tight stop level",
      "note":  "one sentence context"
    },
    "swing": {
      "direction": "LONG or SHORT or SKIP",
      "play":  "specific entry and target for 1-4 week trade",
      "stop":  "swing stop level",
      "note":  "one sentence context"
    },
    "position": {
      "direction": "LONG or SHORT or SKIP",
      "play":  "specific entry and target for 1-3 month trade",
      "stop":  "position stop level",
      "note":  "one sentence context"
    }
  },

  "options_strategy": {
    "name":       "e.g. Bull Call Spread or Long Put or Risk Reversal",
    "legs":       "e.g. Buy USO $73 Call / Sell USO $79 Call",
    "expiry":     "use the expiry date from the data provided",
    "iv_context": "comment on whether IV is cheap or expensive and why this structure suits it",
    "max_loss":   "estimated max loss in dollars per contract",
    "max_gain":   "estimated max gain in dollars per contract",
    "breakeven":  "breakeven USO price"
  },

  "key_support":    "key support level with basis",
  "key_resistance": "key resistance level with basis",
  "risk_case":      "one sentence — the scenario that invalidates this trade",
  "action":         "one precise sentence — exactly what to do, at what price, with what size guidance"
}
""".strip()

_USER_TEMPLATE = """
Here is the real-time market data. Analyse it and return your JSON recommendation.

{market_context}
""".strip()


# ── Helpers ───────────────────────────────────────────────────────────────────

def _extract_json(raw: str) -> dict[str, Any]:
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if match:
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON:\n{raw[:500]}")


def _call_ollama(user: str) -> dict[str, Any]:
    response = ollama.chat(
        model=MODEL,
        messages=[
            {"role": "system", "content": _SYSTEM},
            {"role": "user",   "content": user},
        ],
        format="json",
        options={"temperature": 0.1, "num_ctx": 4096},
    )
    return _extract_json(response["message"]["content"])


# ── Public API ────────────────────────────────────────────────────────────────

def run_analysis(market_context: str) -> dict[str, Any]:
    """
    Run analysis on a pre-formatted market context string.
    market_context should be the output of data_fetcher.snapshot_to_context().
    """
    return _call_ollama(_USER_TEMPLATE.format(market_context=market_context))
