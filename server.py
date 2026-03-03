#!/usr/bin/env python3
"""
server.py — FastAPI web server for the Crude Oil Analyzer.

SSE stream order:
  progress  — one event per fetch step (done=False → done=True)
  market    — partial snapshot after prices (instant ticker)
  news      — Yahoo Finance headlines
  market    — full snapshot after all data fetched
  progress  — AI analysis step
  analysis  — AI trade recommendation
  done
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from data_fetcher import (
    MarketSnapshot, snapshot_to_context,
    _fetch_prices, _fetch_intraday_range, _fetch_technicals,
    _fetch_options, _fetch_news,
)
from tier1_fetcher import (
    Tier1Snapshot, _fetch_eia, _fetch_cot,
    _fetch_baker_hughes, _fetch_opec, _fetch_iea,
)
from analyzer import run_analysis

load_dotenv()

app = FastAPI(title="Crude Oil Analyzer")
TEMPLATE    = Path(__file__).parent / "templates" / "index.html"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def _event(type_: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"


def _snap_to_dict(snap) -> dict:
    return dataclasses.asdict(snap)


async def _stream(model: str):
    loop = asyncio.get_event_loop()
    os.environ["OLLAMA_MODEL"] = model

    snap       = MarketSnapshot()
    snap.tier1 = Tier1Snapshot()
    snap.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    # Each step: (step_id, label, callable)
    steps = [
        (
            "prices",
            "Fetching live prices · WTI, Brent, USO, NatGas, DXY, USD/INR",
            lambda: (_fetch_prices(snap), _fetch_intraday_range(snap)),
        ),
        (
            "technicals",
            "Computing technicals · RSI-14, MACD, Bollinger Bands, moving averages",
            lambda: _fetch_technicals(snap),
        ),
        (
            "options",
            "Fetching USO options chain · IV, put/call ratio, active strikes",
            lambda: _fetch_options(snap),
        ),
        (
            "news",
            "Fetching Yahoo Finance news",
            lambda: _fetch_news(snap),
        ),
        (
            "eia",
            "Fetching EIA Weekly Petroleum Status Report",
            lambda: _fetch_eia(snap.tier1),
        ),
        (
            "cot",
            "Fetching CFTC Commitment of Traders · WTI managed money",
            lambda: _fetch_cot(snap.tier1),
        ),
        (
            "bh",
            "Fetching Baker Hughes North America rig count",
            lambda: _fetch_baker_hughes(snap.tier1),
        ),
        (
            "opec_iea",
            "Fetching OPEC Monthly Report · IEA Oil Market Report",
            lambda: (_fetch_opec(snap.tier1), _fetch_iea(snap.tier1)),
        ),
    ]

    try:
        for step_id, label, fn in steps:
            yield _event("progress", step=step_id, message=label, done=False)
            await loop.run_in_executor(None, fn)
            yield _event("progress", step=step_id, message=label, done=True)

            # After prices: push partial snapshot so ticker populates immediately
            if step_id == "prices":
                yield _event("market", data=_snap_to_dict(snap))

            # After news: push headlines
            if step_id == "news":
                yield _event("news", items=[dataclasses.asdict(n) for n in snap.news])

        # Full snapshot after all data fetched (fills technicals, options, tier1)
        yield _event("market", data=_snap_to_dict(snap))

        # AI analysis
        ai_label = f"Running AI analysis with {model} · this may take 30–120 s"
        yield _event("progress", step="ai", message=ai_label, done=False)
        context = snapshot_to_context(snap)
        result  = await loop.run_in_executor(None, lambda: run_analysis(context))
        yield _event("progress", step="ai", message="AI analysis complete", done=True)

        yield _event("analysis", data=result)
        yield _event("done")

    except Exception as exc:
        yield _event("error", message=str(exc))


@app.get("/", response_class=HTMLResponse)
async def index():
    return HTMLResponse(TEMPLATE.read_text())


@app.get("/api/analyze")
async def analyze(model: str = Query(default="llama3.2")):
    return StreamingResponse(
        _stream(model=model),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@app.get("/api/models")
async def list_models():
    import requests
    try:
        resp   = requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        models = [m["name"] for m in resp.json().get("models", [])]
        return {"models": models}
    except Exception:
        return {"models": [], "error": "Ollama not reachable"}


if __name__ == "__main__":
    import argparse
    p = argparse.ArgumentParser()
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    print(f"\n  Crude Oil Analyzer  →  http://localhost:{args.port}\n")
    uvicorn.run(app, host=args.host, port=args.port)
