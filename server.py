#!/usr/bin/env python3
"""
server.py — FastAPI web server for the Crude Oil Analyzer.

SSE stream order:
  1. status   — progress messages
  2. market   — live prices, technicals, options (from yfinance)
  3. news     — Yahoo Finance headlines
  4. analysis — AI trade recommendation
  5. done
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import os
from pathlib import Path

import uvicorn
from dotenv import load_dotenv
from fastapi import FastAPI, Query
from fastapi.responses import HTMLResponse, StreamingResponse

from data_fetcher import fetch_market_snapshot, snapshot_to_context
from analyzer import run_analysis

load_dotenv()

app = FastAPI(title="Crude Oil Analyzer")
TEMPLATE    = Path(__file__).parent / "templates" / "index.html"
OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


def _event(type_: str, **kwargs) -> str:
    return f"data: {json.dumps({'type': type_, **kwargs})}\n\n"


def _snap_to_dict(snap) -> dict:
    """Serialize MarketSnapshot to a plain dict for SSE."""
    d = dataclasses.asdict(snap)
    # Convert NewsItem list to plain dicts (already done by asdict)
    return d


async def _stream(model: str):
    loop = asyncio.get_event_loop()
    os.environ["OLLAMA_MODEL"] = model

    try:
        # 1. Fetch live market data
        yield _event("status", message="Fetching live prices from Yahoo Finance…")
        snap = await loop.run_in_executor(None, fetch_market_snapshot)

        # 2. Send market data to the browser immediately
        yield _event("market", data=_snap_to_dict(snap))

        # 3. Send news
        yield _event("news", items=[dataclasses.asdict(n) for n in snap.news])

        # 4. Run AI analysis
        yield _event("status", message="Running analysis…")
        context = snapshot_to_context(snap)
        result  = await loop.run_in_executor(None, lambda: run_analysis(context))
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
