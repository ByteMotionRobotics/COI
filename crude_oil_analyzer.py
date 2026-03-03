#!/usr/bin/env python3
"""
crude_oil_analyzer.py — Real-time crude oil market analysis CLI.

Runs fully locally via Ollama — no API key, no cost.

Dual-lens analysis:
  • Lens 1: Wall Street financial analyst
  • Lens 2: Jeffrey Sachs macro-development framework

Usage:
    python crude_oil_analyzer.py [OPTIONS]

Options:
    --google-max N      Max articles per Google News query      (default: 5)
    --twitter-max N     Max tweets per Twitter query            (default: 5)
    --skip-twitter      Skip Twitter even if token is set
    --news-only         Print scraped news feed and exit
    --standard-only     Run only the Wall Street lens
    --sachs-only        Run only the Sachs lens
    --json              Dump raw JSON analysis to stdout
    --model NAME        Ollama model to use (default: llama3.2)

Environment variables (all optional):
    OLLAMA_MODEL            Override the default Ollama model
    OLLAMA_HOST             Ollama server URL (default: http://localhost:11434)
    TWITTER_BEARER_TOKEN    Twitter API v2 bearer token

Setup:
    ollama pull llama3.2
    pip install -r requirements.txt
    python crude_oil_analyzer.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys

import requests as _requests
from dotenv import load_dotenv

# Local modules
from scrapers import fetch_all_news, articles_to_text
from analyzer import run_standard_analysis, run_sachs_analysis
from report import (
    console,
    print_header,
    print_news_feed,
    print_standard_report,
    print_sachs_report,
    print_comparison,
)

load_dotenv()

OLLAMA_HOST = os.getenv("OLLAMA_HOST", "http://localhost:11434")


# ── Guards ────────────────────────────────────────────────────────────────────

def _check_ollama(model: str) -> None:
    """Verify Ollama is running and the requested model is available."""
    try:
        resp = _requests.get(f"{OLLAMA_HOST}/api/tags", timeout=3)
        resp.raise_for_status()
    except Exception:
        console.print(
            "[bold red]Error:[/bold red] Ollama server not reachable at "
            f"[dim]{OLLAMA_HOST}[/dim]\n"
            "Start it with:  [bold]ollama serve[/bold]",
            highlight=False,
        )
        sys.exit(1)

    available = [m["name"] for m in resp.json().get("models", [])]
    # Match on base name (ignore tag suffix for friendlier UX)
    base = model.split(":")[0]
    if not any(base in m for m in available):
        console.print(
            f"[bold red]Error:[/bold red] Model [bold]{model}[/bold] not found.\n"
            f"Pull it with:  [bold]ollama pull {model}[/bold]\n\n"
            f"Available models: {', '.join(available) or 'none'}",
            highlight=False,
        )
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────

def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="crude_oil_analyzer",
        description="Real-time crude oil market analysis — dual-lens, fully local via Ollama",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--google-max",    type=int, default=5,
                   metavar="N", help="Max articles per Google News query (default: 5)")
    p.add_argument("--twitter-max",   type=int, default=5,
                   metavar="N", help="Max tweets per Twitter query (default: 5)")
    p.add_argument("--skip-twitter",  action="store_true",
                   help="Skip Twitter scraping entirely")
    p.add_argument("--news-only",     action="store_true",
                   help="Print scraped news feed and exit (no LLM calls)")
    p.add_argument("--standard-only", action="store_true",
                   help="Run only the Wall Street analyst lens")
    p.add_argument("--sachs-only",    action="store_true",
                   help="Run only the Jeffrey Sachs lens")
    p.add_argument("--json",          action="store_true",
                   help="Dump raw JSON analysis objects to stdout")
    p.add_argument("--model",         type=str, default=None,
                   metavar="NAME",
                   help="Ollama model name (default: llama3.2 or $OLLAMA_MODEL)")
    return p.parse_args()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    args = _parse_args()

    # Allow --model flag to override env var
    if args.model:
        os.environ["OLLAMA_MODEL"] = args.model

    # Resolve the model name (after potential override above)
    import analyzer
    model_name = analyzer.MODEL

    # ── 1. Scrape news (no server needed) ────────────────────────────────────
    console.print("\n[dim]Scraping Google News…[/dim]")

    if args.skip_twitter:
        os.environ.pop("TWITTER_BEARER_TOKEN", None)

    news = fetch_all_news(
        google_max=args.google_max,
        twitter_max=args.twitter_max,
    )

    google_articles = news.get("google_news", [])
    twitter_articles = news.get("twitter", [])

    if twitter_articles:
        console.print(f"[dim]Scraped {len(twitter_articles)} tweets from Twitter/X.[/dim]")
    else:
        console.print("[dim]Twitter skipped or unavailable (token not set / rate-limited).[/dim]")

    if args.news_only:
        print_header(len(google_articles), len(twitter_articles))
        print_news_feed(news)
        return

    if not google_articles and not twitter_articles:
        console.print("[bold red]No news fetched. Check your network connection.[/bold red]")
        sys.exit(1)

    # ── 2. Check Ollama (only when we need LLM) ───────────────────────────────
    _check_ollama(model_name)
    console.print(f"[dim]Using model: [bold]{model_name}[/bold][/dim]\n")

    news_text = articles_to_text(news)

    # ── 3. Print header + news ────────────────────────────────────────────────
    print_header(len(google_articles), len(twitter_articles))
    print_news_feed(news)

    # ── 4. Run analyses ───────────────────────────────────────────────────────
    run_both  = not args.standard_only and not args.sachs_only
    run_std   = run_both or args.standard_only
    run_sachs = run_both or args.sachs_only

    standard_result: dict = {}
    sachs_result:    dict = {}

    if run_std:
        console.print("[dim]Running Wall Street analysis…[/dim]\n")
        try:
            standard_result = run_standard_analysis(news_text)
        except Exception as exc:
            console.print(f"[red]Wall Street analysis failed:[/red] {exc}")

    if run_sachs:
        console.print("[dim]Running Sachs analysis…[/dim]\n")
        try:
            sachs_result = run_sachs_analysis(news_text)
        except Exception as exc:
            console.print(f"[red]Sachs analysis failed:[/red] {exc}")

    # ── 5. Render reports ──────────���──────────────────────────────────────────
    if args.json:
        output = {}
        if standard_result:
            output["standard"] = standard_result
        if sachs_result:
            output["sachs"] = sachs_result
        print(json.dumps(output, indent=2))
        return

    if standard_result:
        print_standard_report(standard_result)

    if sachs_result:
        print_sachs_report(sachs_result)

    if standard_result and sachs_result:
        print_comparison(standard_result, sachs_result)


if __name__ == "__main__":
    main()
