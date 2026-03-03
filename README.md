# Crude Oil Analyzer

Real-time crude oil market intelligence — live prices, technicals, options data, and an AI trade recommendation — delivered as a web app running entirely on your machine.

---

## What It Does

On each analysis run the tool:

1. **Fetches live market data** from Yahoo Finance via `yfinance`
   - WTI crude (CL=F), Brent (BZ=F), USO ETF, Natural Gas (NG=F), Dollar Index (DXY)
   - RSI-14, 20/50/200-day moving averages, MACD, Bollinger Bands, volume ratio
   - USO options chain — put/call ratio, ATM implied volatility, most active strikes, nearest ~45 DTE expiry
   - Yahoo Finance news headlines attached to CL=F, BZ=F, USO

2. **Runs AI analysis** locally via Ollama — no cloud API, no cost, no key required
   - Single unified expert voice combining macro-structural thinking with precise market calls
   - Produces a structured JSON recommendation

3. **Streams results to the browser** via SSE — market data appears immediately, AI analysis follows

---

## Output

Each analysis delivers:

| Section | Detail |
|---|---|
| **Verdict** | LONG / SHORT / HOLD with HIGH / MEDIUM / LOW conviction |
| **Thesis** | 2–3 sentence core argument grounded in real data |
| **Entry zone** | Specific price range to enter |
| **Stop & targets** | Stop loss + two price targets with rationale |
| **Risk/reward** | Calculated ratio to each target |
| **Timeframes** | Separate scalp (1–3 day), swing (1–4 week), position (1–3 month) plays |
| **Options strategy** | Named structure (e.g. Bull Call Spread), legs, expiry, IV context, max loss/gain, breakeven |
| **Technicals** | RSI, MACD status, Bollinger Band position, MA alignment, volume |
| **Key levels** | Support and resistance with basis |
| **Risk case** | One sentence — what invalidates the trade |
| **Action** | One precise sentence — exactly what to do and at what price |

---

## Architecture

```
crude_oil_analyzer/
├── server.py            FastAPI web server — SSE streaming endpoint
├── data_fetcher.py      yfinance data collector — prices, technicals, options, news
├── analyzer.py          Ollama AI analysis — structured JSON trade recommendation
├── templates/
│   └── index.html       Web UI — live ticker bar, timeframe tabs, options card, technicals
├── requirements.txt     Python dependencies
└── .env.example         Environment variable template
```

### Data flow

```
yfinance ──► fetch_market_snapshot() ──► SSE "market" event ──► browser ticker + technicals
                                     └──► snapshot_to_context() ──► Ollama ──► SSE "analysis" event ──► browser recommendation
```

The market data is sent to the browser immediately. AI analysis streams behind it.

---

## Prerequisites

- Python 3.10 or newer
- [Ollama](https://ollama.com) installed and running locally
- At least one Ollama model pulled (default: `llama3.2`)

No API keys. No cloud services. Everything runs on your machine.

---

## Installation

```bash
git clone <repo-url>
cd crude_oil_analyzer

# Install dependencies
python3 -m pip install -r requirements.txt

# Pull the default model (one-time, ~2 GB)
ollama pull llama3.2
```

---

## Running

```bash
python3 server.py
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

### Options

```bash
# Custom host / port
python3 server.py --host 127.0.0.1 --port 9000
```

### Using a different Ollama model

The model selector in the UI lists all models currently pulled in Ollama.
You can also set a default via environment variable:

```bash
OLLAMA_MODEL=mistral python3 server.py
```

Larger models (e.g. `llama3.1:70b`, `mixtral`) produce more nuanced analysis.
The default `llama3.2` (3B) is fast and works well for structured JSON output.

---

## Configuration

Copy `.env.example` to `.env` for persistent settings:

```bash
cp .env.example .env
```

```env
# Ollama host (default: http://localhost:11434)
OLLAMA_HOST=http://localhost:11434

# Default model (overridden by UI selector)
OLLAMA_MODEL=llama3.2
```

---

## Market Data

All data is fetched from Yahoo Finance via `yfinance`. No API key required.

| Symbol | Instrument |
|---|---|
| `CL=F` | WTI crude oil futures |
| `BZ=F` | Brent crude oil futures |
| `USO` | United States Oil Fund ETF (used for options chain) |
| `NG=F` | Natural gas futures |
| `DX-Y.NYB` | US Dollar Index (DXY) |

### Technicals computed from 300-day WTI daily history

| Indicator | Method |
|---|---|
| RSI-14 | Exponential Wilder smoothing |
| MA-20 / MA-50 / MA-200 | Simple rolling mean |
| MACD | EMA(12) − EMA(26), signal = EMA(9) |
| Bollinger Bands | 20-day MA ± 2 standard deviations |
| Volume ratio | Today's volume / 20-day average volume |

### Options (USO chain)

- Selects the expiry closest to 45 DTE (between 15 and 90 days out)
- Put/call ratio computed from total open interest
- ATM implied volatility from the call nearest to the current USO price
- Most active call and put strikes by volume

---

## SSE Event Stream

The `/api/analyze` endpoint streams events in this order:

| Event | Payload | When |
|---|---|---|
| `status` | `message: string` | Progress updates |
| `market` | Full `MarketSnapshot` dict | Immediately after data fetch |
| `news` | Array of news items | With market data |
| `analysis` | Full recommendation JSON | After Ollama completes |
| `done` | — | Stream complete |
| `error` | `message: string` | On failure |

---

## API

### `GET /`
Returns the web UI.

### `GET /api/analyze?model=llama3.2`
SSE stream. Optional `model` query parameter selects the Ollama model.

### `GET /api/models`
Returns a list of models available in the local Ollama instance.

```json
{ "models": ["llama3.2", "mistral", "llama3.1:70b"] }
```

---

## Troubleshooting

**`Ollama not reachable`**
Ensure Ollama is running: `ollama serve`. The model list in the UI will show an error if Ollama is offline; the analysis button will still attempt the request.

**Analysis returns empty or malformed fields**
The default `llama3.2` (3B) model handles the schema reliably. If using a smaller model, try switching to `llama3.2` in the UI selector.

**`Port 8000 already in use`**
```bash
lsof -ti :8000 | xargs kill -9
python3 server.py
```

**No prices displayed**
Yahoo Finance occasionally rate-limits or returns incomplete data. Wait a moment and click Analyze again. The `data_quality` field in the ticker bar shows `live` or `degraded`.

**News section empty**
Yahoo Finance ticker news availability varies by market session. The analysis runs regardless — news is supplementary context.

---

## Dependencies

| Package | Purpose |
|---|---|
| `yfinance` | Live prices, technicals, options chain, Yahoo Finance news |
| `pandas` | Timeseries manipulation for technical indicators |
| `ollama` | Local LLM inference client |
| `fastapi` | Web framework and SSE streaming |
| `uvicorn` | ASGI server |
| `requests` | Ollama model list API call |
| `python-dotenv` | `.env` file loading |
| `feedparser` | (legacy) Google News RSS — no longer used by web server |
| `rich` | (legacy) Terminal rendering — no longer used by web server |

---

## Disclaimer

This tool is for **informational and research purposes only**.
It is not financial advice. Do not make investment or trading decisions based solely on its output. Market analysis produced by AI systems may be incomplete, inaccurate, or delayed. Always consult a qualified financial professional before making investment decisions.
