"""
data_fetcher.py — Real market data via yfinance + Tier 1 reports.

Fetches:
  • Live prices:   WTI (CL=F), Brent (BZ=F), USO ETF, DXY, Natural Gas
  • Technicals:    RSI-14, MA-20/50/200, MACD signal, volume ratio
  • Options:       USO put/call ratio, ATM IV, active strikes, DTE
  • News:          Yahoo Finance ticker news (CL=F, USO, BZ=F)
  • Tier 1:        EIA weekly, CFTC COT, Baker Hughes rig count, OPEC/IEA

All fields degrade gracefully — partial data is always returned.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime, timezone

import pandas as pd
import yfinance as yf

from tier1_fetcher import Tier1Snapshot, fetch_tier1_snapshot, tier1_to_context


# ── Data model ────────────────────────────────────────────────────────────────

@dataclass
class NewsItem:
    title: str
    published: str
    source: str = "Yahoo Finance"


@dataclass
class MarketSnapshot:
    # ── Prices ────────────────────────────────────────────────
    wti_price:         float = 0.0
    wti_prev_close:    float = 0.0
    wti_change:        float = 0.0
    wti_change_pct:    float = 0.0
    wti_day_high:      float = 0.0
    wti_day_low:       float = 0.0
    wti_52w_high:      float = 0.0
    wti_52w_low:       float = 0.0

    brent_price:       float = 0.0
    brent_change_pct:  float = 0.0

    uso_price:         float = 0.0
    uso_change_pct:    float = 0.0

    nat_gas:           float = 0.0
    nat_gas_pct:       float = 0.0

    dollar_idx:        float = 0.0
    dollar_pct:        float = 0.0

    # ── Technicals (computed from WTI daily history) ───────────
    rsi_14:            float = 0.0
    ma_20:             float = 0.0
    ma_50:             float = 0.0
    ma_200:            float = 0.0
    pct_vs_ma20:       float = 0.0   # % above/below 20-day MA
    macd_line:         float = 0.0
    macd_signal_line:  float = 0.0
    macd_bullish:      bool  = False
    volume_ratio:      float = 0.0   # today vs 20-day avg
    bb_upper:          float = 0.0   # Bollinger Band upper
    bb_lower:          float = 0.0

    # ── Options (USO chain) ───────────────────────────────────
    options_expiry:    str   = ""
    options_dte:       int   = 0
    put_call_ratio:    float = 0.0
    atm_iv:            float = 0.0   # % implied vol
    top_call_strike:   str   = ""
    top_put_strike:    str   = ""
    uso_atm_strike:    float = 0.0

    # ── News ──────────────────────────────────────────────────
    news: list[NewsItem] = field(default_factory=list)

    # ── Tier 1 reports ────────────────────────────────────────
    tier1: Tier1Snapshot = field(default_factory=Tier1Snapshot)

    # ── Meta ──────────────────────────────────────────────────
    timestamp:        str   = ""
    market_hours:     str   = ""    # "regular" | "pre" | "post" | "closed"
    data_quality:     str   = "live"


# ── Technicals helpers ────────────────────────────────────────────────────────

def _rsi(series: pd.Series, period: int = 14) -> float:
    delta = series.diff().dropna()
    gain  = delta.clip(lower=0).ewm(com=period - 1, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(com=period - 1, min_periods=period).mean()
    rs    = gain / loss.replace(0, float("nan"))
    rsi   = 100 - 100 / (1 + rs)
    return round(float(rsi.iloc[-1]), 1) if not rsi.empty else 0.0


def _macd(series: pd.Series):
    ema12 = series.ewm(span=12, adjust=False).mean()
    ema26 = series.ewm(span=26, adjust=False).mean()
    line  = ema12 - ema26
    sig   = line.ewm(span=9, adjust=False).mean()
    return float(line.iloc[-1]), float(sig.iloc[-1])


def _bollinger(series: pd.Series, window: int = 20) -> tuple[float, float]:
    ma  = series.rolling(window).mean()
    std = series.rolling(window).std()
    return float((ma + 2 * std).iloc[-1]), float((ma - 2 * std).iloc[-1])


# ── Fetch helpers ─────────────────────────────────────────────────────────────

def _pct_change(current: float, prev: float) -> float:
    if prev == 0:
        return 0.0
    return round((current - prev) / prev * 100, 2)


def _safe_float(val) -> float:
    try:
        f = float(val)
        return 0.0 if math.isnan(f) or math.isinf(f) else f
    except Exception:
        return 0.0


def _fetch_one_price(sym: str) -> tuple[float, float]:
    """Return (last_close, prev_close) for a symbol. Uses history() for reliability."""
    hist = yf.Ticker(sym).history(period="5d", interval="1d", auto_adjust=True)
    closes = hist["Close"].dropna()
    if len(closes) >= 2:
        return _safe_float(closes.iloc[-1]), _safe_float(closes.iloc[-2])
    if len(closes) == 1:
        return _safe_float(closes.iloc[-1]), _safe_float(closes.iloc[-1])
    return 0.0, 0.0


def _fetch_prices(snap: MarketSnapshot) -> None:
    pairs = [
        ("CL=F",     "wti"),
        ("BZ=F",     "brent"),
        ("USO",      "uso"),
        ("NG=F",     "nat_gas"),
        ("DX-Y.NYB", "dollar"),
    ]
    for sym, key in pairs:
        try:
            cur, prev = _fetch_one_price(sym)
            if key == "wti":
                snap.wti_price      = cur
                snap.wti_prev_close = prev
                snap.wti_change     = round(cur - prev, 2)
                snap.wti_change_pct = _pct_change(cur, prev)
            elif key == "brent":
                snap.brent_price      = cur
                snap.brent_change_pct = _pct_change(cur, prev)
            elif key == "uso":
                snap.uso_price      = cur
                snap.uso_change_pct = _pct_change(cur, prev)
            elif key == "nat_gas":
                snap.nat_gas     = cur
                snap.nat_gas_pct = _pct_change(cur, prev)
            elif key == "dollar":
                snap.dollar_idx = cur
                snap.dollar_pct = _pct_change(cur, prev)
        except Exception:
            snap.data_quality = "degraded"


def _fetch_intraday_range(snap: MarketSnapshot) -> None:
    try:
        wti = yf.Ticker("CL=F")
        info = wti.fast_info
        snap.wti_day_high = _safe_float(getattr(info, "day_high",  0))
        snap.wti_day_low  = _safe_float(getattr(info, "day_low",   0))
        snap.wti_52w_high = _safe_float(getattr(info, "year_high", 0))
        snap.wti_52w_low  = _safe_float(getattr(info, "year_low",  0))
    except Exception:
        pass


def _fetch_technicals(snap: MarketSnapshot) -> None:
    try:
        hist = yf.Ticker("CL=F").history(period="300d", interval="1d")
        if hist.empty or len(hist) < 30:
            return

        close = hist["Close"]
        vol   = hist["Volume"]

        snap.rsi_14  = _rsi(close)
        snap.ma_20   = round(float(close.rolling(20).mean().iloc[-1]),  2)
        snap.ma_50   = round(float(close.rolling(50).mean().iloc[-1]),  2)
        snap.ma_200  = round(float(close.rolling(200).mean().iloc[-1]), 2) if len(close) >= 200 else 0.0

        if snap.wti_price and snap.ma_20:
            snap.pct_vs_ma20 = _pct_change(snap.wti_price, snap.ma_20)

        snap.macd_line, snap.macd_signal_line = _macd(close)
        snap.macd_bullish = snap.macd_line > snap.macd_signal_line

        snap.bb_upper, snap.bb_lower = _bollinger(close)

        avg_vol = vol.rolling(20).mean().iloc[-1]
        if avg_vol > 0:
            snap.volume_ratio = round(float(vol.iloc[-1]) / float(avg_vol), 2)

    except Exception:
        snap.data_quality = "degraded"


def _fetch_options(snap: MarketSnapshot) -> None:
    try:
        uso = yf.Ticker("USO")
        expiries = uso.options
        if not expiries:
            return

        now = datetime.now()
        # Find expiry closest to 45 DTE
        scored = []
        for exp in expiries:
            try:
                dte = (datetime.strptime(exp, "%Y-%m-%d") - now).days
                if 15 <= dte <= 90:
                    scored.append((abs(dte - 45), dte, exp))
            except ValueError:
                pass

        if not scored:
            scored = [(0, 0, expiries[0])]
        _, dte, chosen = min(scored)

        snap.options_expiry = chosen
        snap.options_dte    = dte

        chain = uso.option_chain(chosen)
        calls, puts = chain.calls, chain.puts

        # Put/call ratio by open interest
        total_call_oi = calls["openInterest"].fillna(0).sum()
        total_put_oi  = puts["openInterest"].fillna(0).sum()
        if total_call_oi > 0:
            snap.put_call_ratio = round(total_put_oi / total_call_oi, 2)

        # ATM implied vol
        if snap.uso_price > 0:
            snap.uso_atm_strike = snap.uso_price
            calls["dist"] = abs(calls["strike"] - snap.uso_price)
            atm_row = calls.loc[calls["dist"].idxmin()]
            snap.atm_iv = round(_safe_float(atm_row.get("impliedVolatility", 0)) * 100, 1)

        # Most active by volume
        if not calls.empty:
            top_c = calls.loc[calls["volume"].fillna(0).idxmax()]
            snap.top_call_strike = f"${top_c['strike']:.1f}"
        if not puts.empty:
            top_p = puts.loc[puts["volume"].fillna(0).idxmax()]
            snap.top_put_strike = f"${top_p['strike']:.1f}"

    except Exception:
        pass   # Options data is optional


def _fetch_news(snap: MarketSnapshot) -> None:
    seen: set[str] = set()
    items: list[NewsItem] = []

    for sym in ["CL=F", "BZ=F", "USO"]:
        try:
            raw_news = yf.Ticker(sym).news or []
            for a in raw_news:
                # yfinance ≥ 0.2.50 nests content under "content" key
                content = a.get("content", a)
                title = content.get("title") or a.get("title", "")
                uid   = a.get("id") or a.get("uuid") or title
                if not title or uid in seen:
                    continue
                seen.add(uid)

                # Publish time
                pt = content.get("pubDate") or a.get("providerPublishTime")
                if isinstance(pt, (int, float)):
                    pub = datetime.fromtimestamp(pt, tz=timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
                elif isinstance(pt, str):
                    pub = pt[:16]
                else:
                    pub = ""

                items.append(NewsItem(title=title, published=pub))
        except Exception:
            continue

    snap.news = sorted(items, key=lambda x: x.published, reverse=True)[:20]


# ── Public API ────────────────────────────────────────────────────────────────

def fetch_market_snapshot() -> MarketSnapshot:
    """Fetch full market snapshot. All sections degrade gracefully."""
    snap = MarketSnapshot()
    snap.timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    _fetch_prices(snap)
    _fetch_intraday_range(snap)
    _fetch_technicals(snap)
    _fetch_options(snap)
    _fetch_news(snap)
    snap.tier1 = fetch_tier1_snapshot()

    return snap


def snapshot_to_context(snap: MarketSnapshot) -> str:
    """Convert a MarketSnapshot to a structured text block for the AI."""

    def pct(v: float) -> str:
        sign = "+" if v >= 0 else ""
        return f"{sign}{v:.1f}%"

    def price(v: float) -> str:
        return f"${v:.2f}" if v else "N/A"

    lines = [
        "=== LIVE MARKET DATA ===",
        f"WTI Crude   (CL=F): {price(snap.wti_price)}  {pct(snap.wti_change_pct)} | "
        f"Day: {price(snap.wti_day_low)} – {price(snap.wti_day_high)} | "
        f"52w: {price(snap.wti_52w_low)} – {price(snap.wti_52w_high)}",
        f"Brent Crude (BZ=F): {price(snap.brent_price)}  {pct(snap.brent_change_pct)}",
        f"USO ETF:            {price(snap.uso_price)}  {pct(snap.uso_change_pct)}",
        f"Natural Gas (NG=F): {price(snap.nat_gas)}  {pct(snap.nat_gas_pct)}",
        f"Dollar Index (DXY): {snap.dollar_idx:.1f}  {pct(snap.dollar_pct)}",
        "",
        "=== TECHNICALS (WTI Daily) ===",
        f"RSI-14:       {snap.rsi_14}  {'⚠ overbought' if snap.rsi_14 > 70 else '⚠ oversold' if snap.rsi_14 < 30 else 'neutral'}",
        f"vs 20-day MA: {price(snap.ma_20)}  → price is {pct(snap.pct_vs_ma20)} {'above' if snap.pct_vs_ma20 >= 0 else 'below'}",
        f"50-day MA:    {price(snap.ma_50)}",
        f"200-day MA:   {price(snap.ma_200)}",
        f"MACD:         {'Bullish crossover' if snap.macd_bullish else 'Bearish crossover'}  "
        f"(MACD {snap.macd_line:.2f} vs Signal {snap.macd_signal_line:.2f})",
        f"Bollinger:    Upper {price(snap.bb_upper)}  Lower {price(snap.bb_lower)}",
        f"Volume:       {snap.volume_ratio:.1f}x 20-day average",
        "",
        "=== OPTIONS (USO) ===",
        f"Next expiry: {snap.options_expiry}  ({snap.options_dte} DTE)",
        f"Put/Call ratio: {snap.put_call_ratio}  "
        f"({'bullish bias' if snap.put_call_ratio < 0.8 else 'bearish bias' if snap.put_call_ratio > 1.2 else 'neutral'})",
        f"ATM Implied Volatility: {snap.atm_iv}%  "
        f"({'elevated — favour spreads' if snap.atm_iv > 35 else 'moderate' if snap.atm_iv > 20 else 'low — favour buying options'})",
        f"Most active call: {snap.top_call_strike}  |  Most active put: {snap.top_put_strike}",
        f"USO ATM strike (approx): {price(snap.uso_atm_strike)}",
        "",
    ]

    if snap.news:
        lines.append("=== RECENT NEWS (Yahoo Finance) ===")
        for n in snap.news[:12]:
            lines.append(f"  [{n.published}]  {n.title}")

    lines.append("")
    lines.append(tier1_to_context(snap.tier1))

    lines.append(f"\nData timestamp: {snap.timestamp}  Quality: {snap.data_quality}")
    return "\n".join(lines)
