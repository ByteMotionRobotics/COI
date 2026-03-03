"""
report.py — Rich terminal output for the dual-lens crude oil analysis.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich.align import Align
from rich.columns import Columns
from rich.console import Console
from rich.panel import Panel
from rich.rule import Rule
from rich.table import Table
from rich.text import Text
from rich import box

console = Console()


# ── Helpers ───────────────────────────────────────────────────────────────────

_DIRECTION_COLOR = {
    "UP":       "bold green",
    "DOWN":     "bold red",
    "SIDEWAYS": "bold yellow",
}

_CONVICTION_COLOR = {
    "HIGH":   "green",
    "MEDIUM": "yellow",
    "LOW":    "dim",
}

_ARROW = {"UP": "▲", "DOWN": "▼", "SIDEWAYS": "◆"}


def _direction_badge(direction: str) -> Text:
    color = _DIRECTION_COLOR.get(direction, "white")
    arrow = _ARROW.get(direction, "?")
    return Text(f" {arrow} {direction} ", style=f"{color} on grey15")


def _bullet_list(items: list[str], color: str = "white") -> str:
    return "\n".join(f"  [dim]•[/dim] [{color}]{item}[/{color}]" for item in items)


# ── Header ────────────────────────────────────────────────────────────────────

def print_header(article_count: int, twitter_count: int) -> None:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    title = Text("CRUDE OIL MARKET ANALYZER", style="bold white")
    subtitle = Text(
        f"Dual-Lens Analysis  •  {ts}\n"
        f"News: {article_count} Google articles  |  {twitter_count} tweets",
        style="dim",
    )
    console.print()
    console.print(Panel(
        Align.center(title + Text("\n") + subtitle),
        border_style="bright_blue",
        padding=(1, 4),
    ))
    console.print()


# ── Standard Analyst Report ───────────────────────────────────────────────────

def print_standard_report(data: dict[str, Any]) -> None:
    console.print(Rule("[bold cyan] LENS 1 — WALL STREET ANALYST [/bold cyan]", style="cyan"))
    console.print()

    # Price snapshot
    price_table = Table(box=box.SIMPLE_HEAVY, show_header=False, padding=(0, 2))
    price_table.add_column(style="dim")
    price_table.add_column(style="bold white")
    price_table.add_row("WTI (NYMEX)", data.get("current_wti", "—"))
    price_table.add_row("Brent (ICE)", data.get("current_brent", "—"))
    price_table.add_row("Horizon", data.get("time_horizon", "—"))

    direction = data.get("direction", "SIDEWAYS")
    conviction = data.get("conviction", "LOW")
    signal_text = Text()
    signal_text.append(_direction_badge(direction))
    signal_text.append(f"  Conviction: ", style="dim")
    signal_text.append(conviction, style=_CONVICTION_COLOR.get(conviction, "white"))

    console.print(Columns([
        Panel(price_table, title="[dim]Prices[/dim]", border_style="dim", width=36),
        Panel(Align.center(signal_text, vertical="middle"),
              title="[dim]Signal[/dim]", border_style="dim", width=36),
    ]))
    console.print()

    # Key drivers
    drivers = data.get("key_drivers", [])
    if drivers:
        console.print(Panel(
            _bullet_list(drivers, "bright_white"),
            title="[cyan]Key Drivers[/cyan]",
            border_style="cyan",
        ))

    # Supply / demand
    supply = data.get("supply_picture", "")
    demand = data.get("demand_picture", "")
    if supply or demand:
        console.print(Columns([
            Panel(supply, title="[green]Supply[/green]", border_style="green", width=48),
            Panel(demand, title="[yellow]Demand[/yellow]", border_style="yellow", width=48),
        ]))
    console.print()

    # Price targets
    targets = data.get("price_targets", {})
    if targets:
        t = Table(title="Brent Price Targets", box=box.ROUNDED,
                  border_style="dim", show_header=True, header_style="bold")
        t.add_column("Scenario", style="bold")
        t.add_column("Target / Rationale")
        t.add_row("[green]Bull[/green]",  targets.get("bull_case", "—"))
        t.add_row("[yellow]Base[/yellow]", targets.get("base_case", "—"))
        t.add_row("[red]Bear[/red]",   targets.get("bear_case", "—"))
        console.print(t)
    console.print()

    # Tail risks
    risks = data.get("risk_events", [])
    if risks:
        console.print(Panel(
            _bullet_list(risks, "red"),
            title="[red]Tail Risks[/red]",
            border_style="red",
        ))
    console.print()

    # Summary
    summary = data.get("summary", "")
    if summary:
        console.print(Panel(
            f"[italic]{summary}[/italic]",
            title="[cyan]Analyst Summary[/cyan]",
            border_style="cyan",
        ))
    console.print()


# ── Sachs Report ──────────────────────────────────────────────────────────────

def print_sachs_report(data: dict[str, Any]) -> None:
    console.print(Rule("[bold magenta] LENS 2 — JEFFREY SACHS (MACRO / DEVELOPMENT) [/bold magenta]",
                       style="magenta"))
    console.print()

    # Direction: short + long term
    direction_block = data.get("direction", {})
    st = direction_block.get("short_term", "SIDEWAYS")
    lt = direction_block.get("long_term", "SIDEWAYS")
    rationale = direction_block.get("rationale", "")

    direction_text = Text()
    direction_text.append("Short-term  ", style="dim")
    direction_text.append(_direction_badge(st))
    direction_text.append("    Long-term  ", style="dim")
    direction_text.append(_direction_badge(lt))
    if rationale:
        direction_text.append(f"\n\n{rationale}", style="italic dim")

    console.print(Panel(
        Align.center(direction_text, vertical="middle"),
        title="[magenta]Sachs Directional Call[/magenta]",
        border_style="magenta",
        padding=(1, 2),
    ))
    console.print()

    # Root cause + speculative premium
    root = data.get("root_cause", "")
    prem = data.get("speculative_premium", "")
    console.print(Columns([
        Panel(root, title="[magenta]Root Cause[/magenta]", border_style="magenta", width=48),
        Panel(
            f"[bold yellow]{prem}[/bold yellow]",
            title="[yellow]Speculative Premium Estimate[/yellow]",
            border_style="yellow", width=48,
        ),
    ]))
    console.print()

    # Global South alert
    gs = data.get("global_south_alert", {})
    if gs:
        nations = gs.get("most_exposed_nations", [])
        bop = gs.get("bop_pressure", "")
        debt = gs.get("debt_risk", "")
        gs_content = (
            "[bold red]Most Exposed Nations:[/bold red]\n"
            + _bullet_list(nations, "red")
            + f"\n\n[dim]Balance-of-Payments:[/dim] {bop}"
            + f"\n[dim]Debt Risk:[/dim]            {debt}"
        )
        console.print(Panel(
            gs_content,
            title="[red]GLOBAL SOUTH VULNERABILITY ALERT[/red]",
            border_style="red",
        ))
    console.print()

    # Food-energy nexus
    fen = data.get("food_energy_nexus", "")
    if fen:
        console.print(Panel(fen, title="[yellow]Food–Energy–Finance Nexus[/yellow]",
                            border_style="yellow"))
    console.print()

    # Petrodollar + Governance failure (side by side)
    petro = data.get("petrodollar_flows", "")
    gov = data.get("governance_failure", "")
    if petro or gov:
        console.print(Columns([
            Panel(petro, title="[dim]Petrodollar Flows[/dim]", border_style="dim", width=48),
            Panel(gov, title="[dim]Multilateral Governance Failure[/dim]",
                  border_style="dim", width=48),
        ]))
    console.print()

    # Historical parallel + Transition implication
    hist = data.get("historical_parallel", "")
    trans = data.get("transition_implication", "")
    if hist or trans:
        console.print(Columns([
            Panel(hist, title="[dim]Historical Parallel[/dim]", border_style="dim", width=48),
            Panel(trans, title="[green]Energy Transition Implication[/green]",
                  border_style="green", width=48),
        ]))
    console.print()

    # Policy prescriptions
    policy = data.get("policy_prescriptions", [])
    if policy:
        console.print(Panel(
            _bullet_list(policy, "bright_white"),
            title="[magenta]Sachs Policy Prescriptions[/magenta]",
            border_style="magenta",
        ))
    console.print()

    # Sachs verdict
    verdict = data.get("sachs_verdict", "")
    if verdict:
        console.print(Panel(
            f"[italic magenta]{verdict}[/italic magenta]",
            title="[magenta]Sachs Verdict[/magenta]",
            border_style="magenta",
            padding=(1, 2),
        ))
    console.print()


# ── Comparison summary ────────────────────────────────────────────────────────

def print_comparison(standard: dict[str, Any], sachs: dict[str, Any]) -> None:
    console.print(Rule("[bold white] LENS COMPARISON [/bold white]", style="white"))
    console.print()

    std_dir = standard.get("direction", "?")
    sac_st = sachs.get("direction", {}).get("short_term", "?")
    sac_lt = sachs.get("direction", {}).get("long_term", "?")

    t = Table(box=box.ROUNDED, show_header=True, header_style="bold",
              border_style="dim", title="Directional Calls at a Glance")
    t.add_column("Lens")
    t.add_column("Short-Term")
    t.add_column("Long-Term")
    t.add_column("Notes")

    t.add_row(
        "[cyan]Wall Street[/cyan]",
        _direction_badge(std_dir),
        Text("—", style="dim"),
        f"Conviction: {standard.get('conviction', '—')}  |  "
        f"{standard.get('time_horizon', '')}",
    )
    t.add_row(
        "[magenta]Sachs[/magenta]",
        _direction_badge(sac_st),
        _direction_badge(sac_lt),
        "Systems / development lens",
    )

    console.print(Align.center(t))
    console.print()


def print_news_feed(news: dict) -> None:
    """Print a compact news feed summary."""
    google = news.get("google_news", [])
    twitter = news.get("twitter", [])

    console.print(Rule("[dim] NEWS FEED SCRAPED [/dim]", style="dim"))
    console.print()

    if google:
        console.print(f"[dim]Google News ({len(google)} articles):[/dim]")
        for a in google[:8]:
            console.print(f"  [dim]•[/dim] {a.title}  [dim]{a.published[:16]}[/dim]")
        console.print()

    if twitter:
        console.print(f"[dim]Twitter / X ({len(twitter)} tweets):[/dim]")
        for a in twitter[:6]:
            console.print(f"  [dim]•[/dim] [cyan]{a.author}[/cyan]  {a.summary[:80]}")
        console.print()
