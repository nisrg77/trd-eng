# TRDENG — Frontend Data Specification & Visualization Mapping
**Document:** `frtdta.md`  
**Purpose:** Comprehensive guide to all data ingested from the backend into the frontend for real-time charting, telemetry widgets, depth rendering, and performance visualization.

---

## 1. Transport & Architecture Overview

The frontend client (Next.js 14 / React) communicates with the backend via two primary channels:

```
┌────────────────────────────────────────────────────────────────────────┐
│                          BACKEND SERVICES                              │
│                                                                        │
│   [DP / Binance aggTrade WS] ──► [ML Engine] ──► [IFF Overlay Gate]    │
│                                                          │             │
│                                                          ▼             │
│                                                 [Simulated OMS]        │
│                                                          │             │
│                                                          ▼             │
│                                      [FastAPI + WebSocket: Port 8000]  │
└───────────────────────────────────────────────────┬────────────────────┘
                                                    │
                   ┌────────────────────────────────┴──────────────────┐
                   │                                                   │
                   ▼ WebSocket: `/ws/trading?symbol=BTC-USD`           ▼ REST: `/api/...`
┌───────────────────────────────────────────────────┐ ┌───────────────────────────────────┐
│              NEXT.JS 14 FRONTEND (Port 3000)      │ │          REST ENDPOINTS           │
│                                                   │ │                                   │
│  • TradingView Lightweight Charts (Candlesticks)  │ │  • GET  /api/screener/top-stocks  │
│  • Live LOB Order Book & Depth Chart              │ │  • GET  /api/stocks/search?q=...  │
│  • Microstructure VPOC/VAH/VAL & CVD Overlay      │ │  • POST /api/screener/refresh     │
│  • ML Directional Gauge & Model Weights           │ └───────────────────────────────────┘
│  • Account Equity, Margin & P/L Metrics           │
│  • Active Positions with VPOC Snapped Exits       │
│  • Real-Time Execution Logs & Telemetry Stream    │
└───────────────────────────────────────────────────┘
```

- **WebSocket Stream:** `ws://localhost:8000/ws/trading?symbol={symbol}`
  - **Broadcast Cadence:** Continuous loop every **500 ms** (2 Hz updates).
  - **Connection Protocol:** JSON text frames containing `{ "type": string, "payload": object }`.
- **REST Endpoints:** `http://localhost:8000/api/...` for on-demand screener data and asset searches.

---

## 2. WebSocket Real-Time Data Payloads (Categorized for Visualization)

Every WebSocket message has the envelope:
```json
{
  "type": "MESSAGE_TYPE",
  "payload": { ... }
}
```

---

### 2.1 Market Price & Candlesticks (`TICK`)
*Primary Component:* **TradingView Lightweight Charts (`CandlestickChart.tsx`)**

Streamed every 500 ms, aggregating ticks into discrete candlestick bar intervals.

```json
{
  "type": "TICK",
  "payload": {
    "time": 1727068500,
    "open": 64210.50,
    "high": 64225.00,
    "low": 64205.25,
    "close": 64218.75,
    "volume": 14.85
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `time` | `number` | Unix epoch in seconds (5-second bucket). | X-Axis time scale on candlestick chart. |
| `open` | `number` | Opening price for the current 5s bar. | Candle body bottom/top. |
| `high` | `number` | Highest tick in the 5s interval. | Upper candle wick. |
| `low` | `number` | Lowest tick in the 5s interval. | Lower candle wick. |
| `close` | `number` | Latest mark price. | Current candle close + Live Price line header. |
| `volume` | `number` | Accumulated traded volume in interval. | Vertical volume histogram beneath candles. |

**Visualization Hints:**
- **Green Candle:** `close >= open` (`#10b981` / Emerald).
- **Red Candle:** `close < open` (`#f43f5e` / Rose).
- Crosshairs render OHLC summary and percentage change against bar open.

---

### 2.2 Limit Order Book & Market Depth (`ORDER_BOOK`)
*Primary Component:* **Live LOB Ladder & Depth Chart (`OrderBook.tsx`)**

Provides 10 levels of bid and ask market depth with cumulative totals.

```json
{
  "type": "ORDER_BOOK",
  "payload": {
    "bids": [
      { "price": 64215.00, "size": 1.425, "total": 1.425 },
      { "price": 64213.50, "size": 2.100, "total": 3.525 },
      { "price": 64212.00, "size": 0.850, "total": 4.375 }
    ],
    "asks": [
      { "price": 64216.50, "size": 0.950, "total": 0.950 },
      { "price": 64218.00, "size": 1.800, "total": 2.750 },
      { "price": 64219.50, "size": 3.200, "total": 5.950 }
    ],
    "spread": 1.50
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `bids` | `array` | Top 10 Buy limit levels, sorted descending by price. | Green buy depth curve and bid ladder rows. |
| `bids[].price` | `number` | Bid limit price. | Left-side price column. |
| `bids[].size` | `number` | Liquidity volume resting at this level. | Volume column and proportional background bar. |
| `bids[].total` | `number` | Cumulative depth from Top-of-Book. | Depth curve Area under curve ($X=\text{price}, Y=\text{total}$). |
| `asks` | `array` | Top 10 Sell limit levels, sorted ascending by price. | Red sell depth curve and ask ladder rows. |
| `asks[].price` | `number` | Ask limit price. | Right-side price column. |
| `asks[].size` | `number` | Liquidity volume resting at this level. | Volume column and proportional background bar. |
| `asks[].total` | `number` | Cumulative depth from Top-of-Book. | Depth curve Area under curve ($X=\text{price}, Y=\text{total}$). |
| `spread` | `number` | `asks[0].price - bids[0].price`. | Central spread banner with BPS spread cost. |

---

### 2.3 Institutional Footprint & Microstructure Overlay (`MICROSTRUCTURE`)
*Primary Component:* **Microstructure Telemetry Widget & Chart Horizontal Overlays**

Streamed from the new `alpha_overlay` module (`vap_cvd.py`, `iff.py`, `cot_bias.py`).

```json
{
  "type": "MICROSTRUCTURE",
  "payload": {
    "symbol": "BTC-USD",
    "vpoc_price": 64215.50,
    "vah": 64580.00,
    "val": 63890.25,
    "cvd_trend": 142.85,
    "cot_zscore": 0.0,
    "flow_score": 0.21,
    "iff_available": true
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `symbol` | `string` | Ticker symbol (`BTC-USD`, `ETH-USD`, `AAPL`, `SPY`). | Active instrument badge. |
| `vpoc_price` | `number \| null` | **Volume Point of Control:** Price bin with the highest accumulated volume. | **Horizontal Purple Dash Line** on the Candlestick Chart (`#8b5cf6`). |
| `vah` | `number \| null` | **Value Area High:** Upper boundary of 70% volume distribution. | **Horizontal Green Dotted Line** (Resistance Level). |
| `val` | `number \| null` | **Value Area Low:** Lower boundary of 70% volume distribution. | **Horizontal Red Dotted Line** (Support Level). |
| `cvd_trend` | `number` | **Cumulative Volume Delta:** Aggressive buy volume minus aggressive sell volume. | Sparkline or meter: Positive = Bullish CVD, Negative = Bearish CVD. |
| `cot_zscore` | `number` | **CFTC Macro Bias:** 52-week normalized Managed Money positioning Z-score. | Horizontal bar gauge from -3.0 (Bearish) to +3.0 (Bullish). |
| `flow_score` | `number` | **Composite Flow Score ($S_{\text{flow}}$):** Blended score $[-1.0, +1.0]$. | Central circular gauge / progress meter with color spectrum. |
| `iff_available` | `boolean` | Flag indicating whether the IFF overlay is online. | Green/Gray status indicator dot in widget header. |

---

### 2.4 Machine Learning Ensemble & Regime Signals (`ML_SIGNAL`)
*Primary Component:* **ML Signal Gauge, Regime Badge & Model Decomposition (`SignalCard.tsx`)**

Emitted whenever the Core Brain produces a new directional prediction.

```json
{
  "type": "ML_SIGNAL",
  "payload": {
    "signal_id": "sig_6a4d57d3",
    "timestamp_generated": 1727068512.482,
    "instrument": "BTC-USD",
    "direction_magnitude": 0.6641,
    "confidence_score": 0.798,
    "regime_flag": "high_volatility",
    "latency_ms": 77.2,
    "flow_score": 0.21,
    "iff_veto": false,
    "per_model": {
      "ridge": 0.5012,
      "xgb": 0.6245,
      "lstm": 0.8120
    },
    "weights_used": {
      "ridge": 0.20,
      "xgb": 0.50,
      "lstm": 0.30
    }
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `direction_magnitude` | `number` | Composite directional strength in $[-1.0, +1.0]$. | **Direction Needle / Gauge**: $+1.0$ (Strong Buy), $0.0$ (Neutral), $-1.0$ (Strong Sell). |
| `confidence_score` | `number` | Inter-model agreement $\times$ magnitude in $[0.0, 1.0]$. | **Confidence Ring / Circular Progress Bar** ($79.8\%$). |
| `regime_flag` | `string` | Detected market regime (`high_volatility`, `trending_up`, `low_volatility`, `neutral`). | **Regime Badge**: Amber for High Vol, Cyan for Trending, Slate for Neutral. |
| `flow_score` | `number` | Real-time IFF composite flow score in $[-1.0, +1.0]$. | Institutional Flow indicator tag. |
| `iff_veto` | `boolean` | True if opposing flow cancelled the ML trade. | **Red Alert Banner**: *"SIGNAL VETOED BY INSTITUTIONAL FLOW"*. |
| `per_model.ridge` | `number` | Ridge regression linear baseline signal $[-1, +1]$. | Sub-bar 1 in Model Decomposition chart. |
| `per_model.xgb` | `number` | XGBoost gradient boosted tree signal $[-1, +1]$. | Sub-bar 2 in Model Decomposition chart. |
| `per_model.lstm` | `number` | 2-layer LSTM sequence prediction $[-1, +1]$. | Sub-bar 3 in Model Decomposition chart. |
| `weights_used` | `object` | Dynamic weights allocated to each model based on regime. | Proportional Pie / Stacked Bar chart ($20\% / 50\% / 30\%$). |
| `latency_ms` | `number` | Inference latency from raw tick to signal publication. | Telemetry badge in milliseconds (e.g. `77.2 ms`). |

---

### 2.5 Account State & Active Leveraged Positions (`ACCOUNT_UPDATE`)
*Primary Component:* **Account Summary Cards & Position Table (`PerformanceWidgets.tsx`)**

Provides mark-to-market portfolio state, leverage, and active position exits.

```json
{
  "type": "ACCOUNT_UPDATE",
  "payload": {
    "equity": 1045.20,
    "balance": 1000.00,
    "realized_pl": 25.50,
    "gross_buying_power": 10452.00,
    "active_drawdown_pct": 1.25,
    "positions": {
      "BTC-USD": {
        "side": "LONG",
        "qty": 0.15,
        "entry_price": 64215.50,
        "current_price": 64346.80,
        "unrealized_pl": 19.70,
        "unrealized_plpc": 2.04,
        "exposure_pct": 9.22,
        "trailing_stop": 63850.00,
        "tp1_target": 64579.50,
        "tp1_reason": "TP1_VAP_SNAP",
        "tp2_target": 64800.00,
        "tp2_reason": "TP2_+2_SIGMA"
      }
    }
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `equity` | `number` | Net Liquidation Value (NLV = Balance + Unrealized P/L). | Top-level KPI Card (`$1,045.20`). |
| `balance` | `number` | Settled cash balance. | Subtitle in Equity Card (`Cash: $1,000.00`). |
| `realized_pl` | `number` | Total historical closed trade P/L. | Realized P/L Card with Green/Red text. |
| `gross_buying_power` | `number` | 10x leveraged purchasing capacity. | Available Buying Power metric. |
| `active_drawdown_pct` | `number` | Trailing drawdown from day start equity. | **Circuit Breaker Progress Bar** vs 3% US / 6% Crypto limit. |
| `positions[symbol]` | `object` | Map of active open contracts. | Rows in the **Active Positions Table**. |
| `pos.side` | `string` | `"LONG"` or `"SHORT"`. | Directional pill (Green for Long, Red for Short). |
| `pos.qty` | `number` | Number of contracts held. | Position size column. |
| `pos.entry_price` | `number` | Average filled execution price. | Horizontal White marker on chart + Table column. |
| `pos.unrealized_pl` | `number` | Live floating mark-to-market dollar profit. | Green/Red dollar return column (`+$19.70`). |
| `pos.unrealized_plpc`| `number` | Live floating percentage return. | Percentage return badge (`+2.04%`). |
| `pos.trailing_stop` | `number` | Dynamic ATR trailing stop price. | **Horizontal Red Line** on price chart. |
| `pos.tp1_target` | `number` | First profit target (closes 40%). | **Horizontal Green Line** on chart + Snapped badge. |
| `pos.tp1_reason` | `string` | Exit logic: `TP1_VAP_SNAP` vs `TP1_+1_SIGMA`. | Structural snap pill (Purple badge if `VAP_SNAP`). |
| `pos.tp2_target` | `number` | Second profit target (closes 30%). | **Horizontal Cyan Line** on chart. |

---

### 2.6 Order Execution & Risk Audit Stream (`EXECUTION`)
*Primary Component:* **Execution Feed & Audit Log Table (`ExecutionLogs.tsx`)**

Emitted whenever an order is submitted, evaluated by Risk Guard, or closed by OMS.

```json
{
  "type": "EXECUTION",
  "payload": {
    "order_id": "ord_55b3c19x",
    "signal_id": "sig_6a4d57d3",
    "instrument": "BTC-USD",
    "action": "BUY",
    "order_type": "LIMIT",
    "price": 64215.50,
    "quantity": 0.15,
    "portfolio_allocation_pct": 2.50,
    "confidence": 0.798,
    "risk_state": "APPROVED",
    "checks_passed": ["drawdown_ok", "exposure_ok", "concentration_ok"],
    "failed_check": null,
    "oms_state": "FILLED",
    "timestamp_executed": 1727068512.505,
    "realized_pnl": 0.0
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `order_id` | `string` | Unique order identifier. | Clickable reference link in audit log. |
| `action` | `string` | `"BUY"` or `"SELL"`. | Colored action pill. |
| `price` | `number` | Filled execution price. | Trade price column. |
| `quantity` | `number` | Number of contracts filled. | Volume filled column. |
| `portfolio_allocation_pct` | `number` | Kelly sizing percentage after IFF multiplier. | Allocation weight meter. |
| `risk_state` | `string` | `"APPROVED"` or `"REJECTED"`. | Green checkmark or Red warning badge. |
| `failed_check` | `string \| null` | Name of limit breached (e.g. `exposure_limit`). | Tooltip explaining why order was blocked. |
| `realized_pnl` | `number` | Realized P/L if this order closed a position. | Exit trade gain/loss banner. |

---

### 2.7 Goal & Risk Gating Module & Quota Tracker (`GOAL_UPDATE` & `QUOTA_UPDATE`)
*Primary Component:* **Evaluation Quota & Win-Rate Tracker (`PerformanceWidgets.tsx`) & Goal & Risk Dashboard**

Tracks monthly ceilings (20 Crypto / 80 US Equities), multi-horizon circuit breakers (4% daily loss, 18% monthly drawdown), dynamic leverage, and expectancy metrics.

#### `GOAL_UPDATE` Payload Structure:
```json
{
  "type": "GOAL_UPDATE",
  "payload": {
    "current_month": "2026-09",
    "crypto_trades_completed": 12,
    "crypto_ceiling": 20,
    "crypto_progress_pct": 60.0,
    "stock_trades_completed": 35,
    "stock_ceiling": 80,
    "stock_progress_pct": 43.8,
    "daily_loss_usd": 12.40,
    "daily_loss_pct": 1.24,
    "daily_loss_limit_pct": 4.0,
    "daily_circuit_breaker_active": false,
    "peak_monthly_equity": 1050.00,
    "current_equity": 1024.50,
    "monthly_drawdown_pct": 2.43,
    "monthly_drawdown_limit_pct": 18.0,
    "monthly_circuit_breaker_active": false,
    "overall_win_rate_pct": 61.7,
    "overall_profit_factor": 1.84
  }
}
```

#### `QUOTA_UPDATE` Payload Structure (Backward Compatibility):
```json
{
  "type": "QUOTA_UPDATE",
  "payload": {
    "crypto": {
      "completed": 12,
      "wins": 8,
      "losses": 4,
      "win_pnl": 94.20,
      "loss_pnl": -35.10
    },
    "futures": {
      "completed": 35,
      "wins": 21,
      "losses": 14,
      "win_pnl": 145.00,
      "loss_pnl": -65.40
    }
  }
}
```

| Field | Type | Derived Metric / Safety Limit | Visualization Mapping |
|---|---|---|---|
| `crypto_trades_completed` / `stock_trades_completed` | `number` | Monthly Trade Ceilings (20 Crypto / 80 Stocks). | Ceilings Progress Bars with auto-throttling indicators. |
| `daily_loss_pct` / `daily_loss_limit_pct` | `number` | **4.0% Daily Loss Circuit Breaker**. | Daily Risk Gauge (Turns Amber > 2.5%, Red if Tripped). |
| `monthly_drawdown_pct` / `monthly_drawdown_limit_pct` | `number` | **18.0% Max Drawdown Circuit Breaker**. | Monthly Drawdown Warning Badge with Peak-to-Trough track. |
| `wins`, `losses` | `number` | **Win Rate %** = `wins / (wins + losses) * 100%`. | Win rate donut chart / Progress badge. |
| `win_pnl`, `loss_pnl` | `number` | **Profit Factor** = `win_pnl / abs(loss_pnl)`. | KPI Metric Badge (e.g. `1.84 Profit Factor`). |

---

### 2.8 7-Day Stock Screener Candidates (`SCREENER_UPDATE`)
*Primary Component:* **US Futures & Equities Hub (`UsFuturesHub.tsx`)**

Periodically broadcast from `stock_screener.py` ranking the top candidate pool.

```json
{
  "type": "SCREENER_UPDATE",
  "payload": {
    "long": ["NVDA", "AAPL", "MSFT"],
    "short": ["INTC", "DIS", "PFE"],
    "timestamp": 1727068200
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `long` | `array` | Top momentum + RVOL weekly buy candidates. | Green pill tags in the Weekly Long Candidate list. |
| `short` | `array` | Bottom momentum + RVOL weekly short candidates. | Red pill tags in the Weekly Short Candidate list. |
| `timestamp` | `number` | Last screener execution epoch. | "Last screened" time label. |

---

## 3. REST API Endpoints (On-Demand Data)

### 3.1 Screener Top Candidates (`GET /api/screener/top-stocks`)
Returns the complete ranked pool of 15 CME Single Stock Future (SSF) candidates.

**Response Schema:**
```json
{
  "timestamp": "2026-09-23T08:15:00Z",
  "next_refresh": "2026-09-30T08:15:00Z",
  "cache_age_days": 1.25,
  "ttl_days": 7,
  "count": 15,
  "top_candidates": [
    {
      "symbol": "NVDA",
      "momentum_20d": 0.0842,
      "rvol": 2.45,
      "alpha_score": 1.892,
      "bias": "LONG",
      "price": 228.85
    },
    {
      "symbol": "INTC",
      "momentum_20d": -0.0615,
      "rvol": 1.82,
      "alpha_score": -1.450,
      "bias": "SHORT",
      "price": 22.50
    }
  ]
}
```
### 2.8 Trading Session & Market Hours Status (`MARKET_SESSION`)
*Primary Component:* **Market Session Banner & Trading Terminal Header (`DashboardPage`, `UsFuturesHub.tsx`)**

Emitted every broadcast cycle to communicate asset-class session state and enforce RTH constraints.

```json
{
  "type": "MARKET_SESSION",
  "payload": {
    "us": {
      "symbol": "SPY",
      "asset_class": "futures",
      "is_open": false,
      "session_name": "CLOSED_OFF_HOURS",
      "timezone": "America/New_York",
      "rth_hours": "Mon-Fri 09:30 - 16:00 ET",
      "ny_time": "Wed 01:48:12 EDT",
      "date": "2026-09-23"
    },
    "crypto": {
      "symbol": "BTC-USD",
      "asset_class": "crypto",
      "is_open": true,
      "session_name": "24/7",
      "timezone": "UTC",
      "rth_hours": "24/7/365",
      "ny_time": "Wed 01:48:12 EDT",
      "date": "2026-09-23"
    },
    "current_symbol": {
      "symbol": "AAPL",
      "is_open": false,
      "session_name": "CLOSED_OFF_HOURS"
    },
    "server_time_utc": "2026-09-23T05:48:12.123456Z"
  }
}
```

| Field | Type | Description | Visualization Mapping |
|---|---|---|---|
| `us.is_open` | `boolean` | `true` during Monday–Friday 09:30–16:00 ET, `false` otherwise. | Green "US OPEN (RTH)" pill vs Amber "US CLOSED (OFF-HOURS)" banner. |
| `us.session_name` | `string` | `"RTH_OPEN"`, `"CLOSED_OFF_HOURS"`, or `"CLOSED_WEEKEND"`. | Session badge in US Futures Hub header. |
| `crypto.is_open` | `boolean` | Always `true` (24/7 continuous crypto trading). | Cyan "CRYPTO 24/7 LIVE" badge. |
| `us.ny_time` | `string` | Live New York local clock time with timezone. | Monospace clock display on US terminal tab. |

---

### 3.3 Market Sessions API (`GET /api/market-sessions`)
Used for initial REST status queries or fallback sync:
- Returns `{"us": {...}, "crypto": {...}, "ny_time": "..."}`.

---

## 4. UI Component to Data Field Mapping Matrix

| UI Component | Primary Data Packets | Visualized Fields | Render Type |
|---|---|---|---|
| **Market Session Banner** | `MARKET_SESSION` | `us.is_open`, `us.session_name`, `us.ny_time`, `crypto.is_open` | Status Pill Banner (Amber for closed, Green for open, Cyan for 24/7) |
| **Candlestick Chart** | `TICK`, `ACCOUNT_UPDATE`, `MICROSTRUCTURE` | `time`, `open`, `high`, `low`, `close`, `vpoc_price`, `vah`, `val`, `trailing_stop`, `tp1_target`, `entry_price` | TradingView Canvas + Horizontal Price Lines |
| **Depth Chart & LOB** | `ORDER_BOOK` | `bids[].price`, `bids[].total`, `asks[].price`, `asks[].total`, `spread` | Dual Area Chart (Green/Red) + Depth Ladder |
| **Signal Meter** | `ML_SIGNAL` | `direction_magnitude`, `confidence_score`, `flow_score`, `iff_veto` | Radial Gauge + Confidence Ring + Alert Banner |
| **Model Ensemble Bar** | `ML_SIGNAL` | `per_model.ridge`, `per_model.xgb`, `per_model.lstm`, `weights_used` | Stacked Horizontal Bar Chart |
| **Account Health Cards** | `ACCOUNT_UPDATE` | `equity`, `balance`, `realized_pl`, `gross_buying_power` | KPI Metric Cards with percentage change |
| **Circuit Breaker Gauge** | `ACCOUNT_UPDATE` | `active_drawdown_pct` vs `3.0%` (US) / `6.0%` (Crypto) | Segmented Progress Meter with Danger Threshold |
| **Position Table** | `ACCOUNT_UPDATE` | `symbol`, `side`, `qty`, `entry_price`, `current_price`, `unrealized_pl`, `tp1_reason` | Interactive Table with Exit Snapping Pills |
| **Execution Log** | `EXECUTION` | `order_id`, `action`, `price`, `quantity`, `risk_state`, `failed_check` | Chronological Real-time Log Stream |
| **Screener Hub** | `SCREENER_UPDATE`, `/api/screener/top-stocks` | `top_candidates[].symbol`, `momentum_20d`, `rvol`, `alpha_score` | Grid Cards with Long/Short Filter Badges |
| **Quota Monitor** | `QUOTA_UPDATE` | `completed`, `wins`, `losses`, `win_pnl`, `loss_pnl` | Progress Bar + Win Rate % + Profit Factor Tag |

---

## 5. UI Color Palette & Visual Style Tokens

To maintain rich institutional aesthetics across visualizations, the frontend adheres to the following hex color definitions:

| Element | Hex Color | Tailwind Class | Semantic Usage |
|---|---|---|---|
| **Background Dark** | `#0b0f19` | `bg-slate-950` | Primary application canvas background |
| **Card Surface** | `#111827` | `bg-slate-900` | Widget backgrounds with subtle borders |
| **Borders & Dividers** | `#1e293b` | `border-slate-800` | Structural container dividers |
| **Bullish / Buy / Long** | `#10b981` | `text-emerald-500` | Up candles, bid depth, buy orders, positive P/L |
| **Bearish / Sell / Short** | `#f43f5e` | `text-rose-500` | Down candles, ask depth, sell orders, negative P/L |
| **VPOC / Microstructure** | `#8b5cf6` | `text-purple-500` | Volume Point of Control, VAP snaps, IFF flow |
| **High Volatility / Alert** | `#f59e0b` | `text-amber-500` | Circuit breaker warnings, high vol regime |
| **Crypto Theme Accent** | `#06b6d4` | `text-cyan-500` | 24/7 crypto indicators, live tick markers |
| **Regulated US Futures** | `#3b82f6` | `text-blue-500` | CME stock futures, RTH indicators |
