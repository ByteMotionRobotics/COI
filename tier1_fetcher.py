"""
tier1_fetcher.py — Bloomberg-grade Tier 1 market reports.

Sources (all free, no paid subscription required):
  • EIA Weekly Petroleum Status Report  — EIA API v2 (free key: eia.gov/opendata)
  • CFTC Commitments of Traders (COT)  — direct CSV download, no key needed
  • Baker Hughes NA Rig Count          — web scrape, no key needed
  • OPEC Monthly Oil Market Report     — web scrape, no key needed
  • IEA Oil Market Report              — RSS, no key needed

All sections degrade gracefully — missing data returns zero/empty, never crashes.
"""

from __future__ import annotations

import io
import os
import re
import zipfile
from dataclasses import dataclass
from datetime import datetime

import pandas as pd
import requests

_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    )
}
_TIMEOUT = 20


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class Tier1Snapshot:
    # EIA Weekly Petroleum Status Report
    eia_report_date:  str   = ""
    cushing_mb:       float = 0.0    # Cushing, OK crude stocks (million barrels)
    cushing_wow:      float = 0.0    # week-over-week change (negative = draw = bullish)
    total_us_mb:      float = 0.0    # total US crude stocks (mb)
    total_us_wow:     float = 0.0    # WoW change
    us_prod_kbpd:     float = 0.0    # US crude production (thousand bpd)
    refinery_util:    float = 0.0    # refinery utilization (%)

    # CFTC Commitment of Traders — WTI Crude Oil, Managed Money
    cot_date:         str   = ""
    mm_net:           int   = 0      # managed money net (long - short contracts)
    mm_long:          int   = 0
    mm_short:         int   = 0
    mm_pct:           float = 0.0    # YTD positioning percentile (0 = max short, 1 = max long)
    mm_signal:        str   = ""     # "extreme long", "extreme short", or "neutral (X%)"

    # Baker Hughes North America Rig Count
    bh_date:          str   = ""
    oil_rigs:         int   = 0      # US oil rig count
    rig_wow:          int   = 0      # week-over-week change

    # OPEC Monthly Oil Market Report
    opec_date:        str   = ""
    opec_headline:    str   = ""

    # IEA Oil Market Report
    iea_date:         str   = ""
    iea_headline:     str   = ""

    data_quality:     str   = "live"


# ── EIA API v2 ────────────────────────────────────────────────────────────────

_EIA_BASE = "https://api.eia.gov/v2"


def _eia_call(key: str, route: str, facets: dict) -> list[dict]:
    params = {
        "api_key": key,
        "data[0]": "value",
        "sort[0][column]": "period",
        "sort[0][direction]": "desc",
        "length": "5",
    }
    params.update(facets)
    try:
        r = requests.get(
            f"{_EIA_BASE}{route}", params=params, timeout=_TIMEOUT, headers=_HEADERS
        )
        return r.json().get("response", {}).get("data", [])
    except Exception:
        return []


def _fetch_eia(t1: Tier1Snapshot) -> None:
    key = os.getenv("EIA_API_KEY", "")
    if not key:
        t1.data_quality = "partial"
        return

    # Cushing, Oklahoma crude stocks
    rows = _eia_call(key, "/petroleum/stoc/wstk/data/", {
        "facets[product][]": "EPC0",
        "facets[area][]":    "Y35NY",
    })
    if len(rows) >= 2:
        t1.cushing_mb      = round(float(rows[0]["value"]), 1)
        t1.cushing_wow     = round(float(rows[0]["value"]) - float(rows[1]["value"]), 1)
        t1.eia_report_date = rows[0]["period"]

    # Total US crude stocks
    rows = _eia_call(key, "/petroleum/stoc/wstk/data/", {
        "facets[product][]": "EPC0",
        "facets[area][]":    "NUS",
    })
    if len(rows) >= 2:
        t1.total_us_mb  = round(float(rows[0]["value"]), 1)
        t1.total_us_wow = round(float(rows[0]["value"]) - float(rows[1]["value"]), 1)

    # US crude production (weekly)
    rows = _eia_call(key, "/petroleum/crd/crpdn/data/", {
        "facets[area][]": "NUS",
    })
    if rows:
        try:
            t1.us_prod_kbpd = round(float(rows[0]["value"]), 1)
        except Exception:
            pass

    # Refinery utilization
    rows = _eia_call(key, "/petroleum/pnp/wiup/data/", {
        "facets[area][]": "NUS",
    })
    if rows:
        try:
            t1.refinery_util = round(float(rows[0]["value"]), 1)
        except Exception:
            pass


# ── CFTC Commitment of Traders ────────────────────────────────────────────────

_COT_URL = "https://www.cftc.gov/dea/newcot/fut_disagg_txt.zip"


def _to_int(val) -> int:
    return int(float(str(val).replace(",", "")))


def _fetch_cot(t1: Tier1Snapshot) -> None:
    try:
        r = requests.get(_COT_URL, timeout=60, headers=_HEADERS)
        r.raise_for_status()
        zf = zipfile.ZipFile(io.BytesIO(r.content))
        fname = next(n for n in zf.namelist() if n.lower().endswith((".txt", ".csv")))
        df = pd.read_csv(zf.open(fname), low_memory=False)

        # WTI crude oil rows
        mask = df["Market_and_Exchange_Names"].str.contains(
            "CRUDE OIL, LIGHT SWEET", na=False, case=False
        )
        wti = df[mask].copy()
        if wti.empty:
            return

        # Sort by whichever date column exists
        for date_col in ("Report_Date_as_YYYY-MM-DD", "As_of_Date_In_Form_YYMMDD",
                         "Report_Date_as_MM_DD_YYYY"):
            if date_col in wti.columns:
                wti = wti.sort_values(date_col)
                t1.cot_date = str(wti[date_col].iloc[-1])
                break

        long_col  = next((c for c in wti.columns if c.startswith("M_Money_Positions_Long")),  None)
        short_col = next((c for c in wti.columns if c.startswith("M_Money_Positions_Short")), None)
        if not long_col or not short_col:
            return

        t1.mm_long  = _to_int(wti[long_col].iloc[-1])
        t1.mm_short = _to_int(wti[short_col].iloc[-1])
        t1.mm_net   = t1.mm_long - t1.mm_short

        # YTD percentile — how extreme is current positioning vs this year
        nets = (wti[long_col].astype(float) - wti[short_col].astype(float)).dropna()
        if len(nets) > 4:
            lo, hi = nets.min(), nets.max()
            t1.mm_pct = round((t1.mm_net - lo) / (hi - lo), 2) if hi != lo else 0.5
            if t1.mm_pct >= 0.85:
                t1.mm_signal = "extreme long — contrarian bearish risk"
            elif t1.mm_pct <= 0.15:
                t1.mm_signal = "extreme short — contrarian bullish signal"
            else:
                t1.mm_signal = f"neutral ({t1.mm_pct:.0%} YTD percentile)"
        else:
            t1.mm_pct    = 0.5
            t1.mm_signal = "insufficient history for percentile"

    except Exception:
        t1.data_quality = "partial"


# ── Baker Hughes Rig Count ────────────────────────────────────────────────────

_BH_URL = "https://rigcount.bakerhughes.com/na-rig-count"


def _fetch_baker_hughes(t1: Tier1Snapshot) -> None:
    try:
        r = requests.get(_BH_URL, timeout=_TIMEOUT, headers=_HEADERS)
        html = r.text

        # Pattern 1: <td>Oil</td><td>480</td><td>483</td>
        m = re.search(
            r'Oil\s*</td>\s*<td[^>]*>\s*(\d+)\s*</td>\s*<td[^>]*>\s*(\d+)',
            html, re.I | re.S
        )
        if m:
            t1.oil_rigs = int(m.group(1))
            t1.rig_wow  = t1.oil_rigs - int(m.group(2))
            t1.bh_date  = datetime.now().strftime("%Y-%m-%d")
            return

        # Pattern 2: JSON-like "oil_rigs": 480
        m = re.search(r'"oil[_\s-]?rigs?"[:\s]+(\d+)', html, re.I)
        if m:
            t1.oil_rigs = int(m.group(1))
            t1.bh_date  = datetime.now().strftime("%Y-%m-%d")
            return

        # Pattern 3: plausible 3-digit number near "oil" keyword
        idx = html.lower().find(">oil<")
        if idx != -1:
            snippet = html[idx:idx + 400]
            nums = [int(n) for n in re.findall(r'\b(\d{3})\b', snippet)
                    if 300 <= int(n) <= 900]
            if nums:
                t1.oil_rigs = nums[0]
                t1.bh_date  = datetime.now().strftime("%Y-%m-%d")

    except Exception:
        t1.data_quality = "partial"


# ── OPEC Monthly Oil Market Report ───────────────────────────────────────────

def _fetch_opec(t1: Tier1Snapshot) -> None:
    try:
        import feedparser
        feed = feedparser.parse("https://www.opec.org/opec_web/en/press_room/4166.htm")
        if feed.entries:
            e = feed.entries[0]
            t1.opec_headline = e.get("title", "")[:200]
            t1.opec_date     = (e.get("published") or "")[:16]
            return
    except Exception:
        pass

    try:
        r = requests.get(
            "https://www.opec.org/opec_web/en/press_room/4166.htm",
            timeout=_TIMEOUT, headers=_HEADERS
        )
        m = re.search(r"OPEC Monthly Oil Market Report[^<\n]{0,160}", r.text, re.I)
        if m:
            t1.opec_headline = m.group(0).strip()
            t1.opec_date     = datetime.now().strftime("%Y-%m")
    except Exception:
        pass


# ── IEA Oil Market Report ─────────────────────────────────────────────────────

def _fetch_iea(t1: Tier1Snapshot) -> None:
    try:
        import feedparser
        feed = feedparser.parse("https://www.iea.org/feed/reports/oil-market-report")
        if feed.entries:
            e = feed.entries[0]
            t1.iea_headline = e.get("title", "")[:200]
            t1.iea_date     = (e.get("published") or "")[:16]
            return
    except Exception:
        pass

    try:
        r = requests.get(
            "https://www.iea.org/reports/oil-market-report",
            timeout=_TIMEOUT, headers=_HEADERS
        )
        m = re.search(r"Oil Market Report[^<\n]{0,160}", r.text, re.I)
        if m:
            t1.iea_headline = m.group(0).strip()
            t1.iea_date     = datetime.now().strftime("%Y-%m")
    except Exception:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_tier1_snapshot() -> Tier1Snapshot:
    """Fetch all Tier 1 report data. All sections degrade gracefully."""
    t1 = Tier1Snapshot()
    _fetch_eia(t1)
    _fetch_cot(t1)
    _fetch_baker_hughes(t1)
    _fetch_opec(t1)
    _fetch_iea(t1)
    return t1


def tier1_to_context(t1: Tier1Snapshot) -> str:
    """Format Tier 1 snapshot as a structured text block for the AI model."""

    def mb(v: float) -> str:
        return f"{v:.1f} mb" if v else "N/A"

    def chg(v: float) -> str:
        if not v:
            return "N/A"
        sign = "+" if v > 0 else ""
        tag  = "(BUILD — bearish)" if v > 0 else "(DRAW — bullish)"
        return f"{sign}{v:.1f} mb {tag}"

    def kbpd(v: float) -> str:
        return f"{v:,.0f} kbpd" if v else "N/A"

    def pct(v: float) -> str:
        return f"{v:.1f}%" if v else "N/A"

    lines = ["=== TIER 1 REPORTS ===", ""]

    # EIA
    if t1.eia_report_date or t1.cushing_mb:
        lines += [
            f"EIA Weekly Petroleum Status Report ({t1.eia_report_date or 'latest'}):",
            f"  Cushing, OK stocks : {mb(t1.cushing_mb)}   WoW: {chg(t1.cushing_wow)}",
            f"  Total US crude     : {mb(t1.total_us_mb)}   WoW: {chg(t1.total_us_wow)}",
            f"  US production      : {kbpd(t1.us_prod_kbpd)}",
            f"  Refinery util      : {pct(t1.refinery_util)}",
            "",
        ]
    else:
        lines += ["EIA: key not configured — add EIA_API_KEY to .env (free: eia.gov/opendata)", ""]

    # CFTC COT
    if t1.mm_net:
        lines += [
            f"CFTC COT — WTI Managed Money ({t1.cot_date or 'latest'}):",
            f"  Net position : {t1.mm_net:+,} contracts",
            f"  Long / Short : {t1.mm_long:,} / {t1.mm_short:,}",
            f"  Signal       : {t1.mm_signal}",
            "",
        ]

    # Baker Hughes
    if t1.oil_rigs:
        wow = f" ({t1.rig_wow:+d} WoW)" if t1.rig_wow else ""
        lines += [
            f"Baker Hughes Rig Count ({t1.bh_date or 'latest'}):",
            f"  US oil rigs: {t1.oil_rigs}{wow}",
            "  Rising rig count → more supply in 6–12 months (lagging bearish signal).",
            "",
        ]

    # OPEC / IEA
    if t1.opec_headline:
        lines.append(f"OPEC MOMR ({t1.opec_date}): {t1.opec_headline}")
    if t1.iea_headline:
        lines.append(f"IEA OMR ({t1.iea_date}): {t1.iea_headline}")

    return "\n".join(lines)
