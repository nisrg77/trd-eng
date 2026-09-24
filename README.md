# TRDENG — Quantitative Algorithmic Execution Engine & Trading Terminal

A high-performance **Prediction Engine**, **Risk Guard**, and **Institutional Trading Terminal** for algorithmic trading, featuring an **Institutional Footprint & Flow (IFF)** overlay, **Goal & Risk Gating Module**, **Dead-Day Filter**, **Dynamic Leverage Curve**, and a **Stitch MCP UI Presentation Layer**.

```
Raw Feed (yfinance + Alpaca REST + Binance aggTrade WS)
   │
   ▼
[DP Pipeline] ──► [Feature Preprocessor] ──► [Ensemble Models: Ridge + XGB + LSTM] ──► [Meta-Aggregator] 
                                                                                            │
[Microstructure (VAP / CVD)] ──────► [IFF Flow Score & Veto Gate] ◄────────────────────────┘
[Macro Bias (CFTC COT)]                     │
                                            ▼
[Dead-Day Filter] ─────────────► [Goal & Risk Gating Module] ──► [Simulated OMS] ──► Stitch MCP UI Terminal
(Chop Session Detection)         (Monthly Ceilings & Circuit Breakers)                (Crypto / US Futures / Logs)
```

---

## System Architecture

| Layer | File | Description |
|---|---|---|
| **STATE** | `core/symbol_state.py` | `SymbolStateRegistry` thread-safe singleton for unified historical state management. |
| **DP** | `data_pipeline/pipeline.py` | yfinance & Alpaca OHLCV + frac-diff, GARCH vol, RSI, OBI (+ Binance `aggTrade` live tick feed). |
| **DEAD-DAY** | `data_pipeline/dead_day_filter.py` | Chop session detector: Range/ATR $< 0.85$, RVOL $< 0.70$, Realized Vol $< 0.008$. Collapses conviction to $0.0$. |
| **PP** | `brain/preprocessor.py` | Rolling Z-score normalisation + imputation. |
| **M1 / M2 / M3** | `brain/models/` | Ridge Regression, XGBoost, and 2-layer LSTM ensemble models. |
| **MA** | `brain/meta_aggregator.py` | Regime-based dynamic weight blending + IFF directional veto/scale. |
| **VAP/CVD** | `alpha_overlay/vap_cvd.py` | 500-bin incremental VAP histogram (VPOC/VAH/VAL) + CVD divergence tracker. |
| **IFF** | `alpha_overlay/iff.py` | Composite Institutional Flow Score ($S_{\text{flow}}$) and Non-blocking 5ms Micro-Buffer Hold Window. |
| **COT** | `alpha_overlay/cot_bias.py` | CFTC Disaggregated COT macro bias tracker (CME futures proxy for crypto). |
| **GOAL & RISK** | `goals/goal_module.py` | Daily Trade Limits (20 Crypto / 80 Stocks per day), Multi-Horizon Circuit Breakers (4% daily loss, 18% monthly drawdown), Dynamic Leverage ($1\times - 5\times$ Crypto / $1\times - 10\times$ Stocks). |
| **SESSION** | `execution/market_session.py` | RTH session gating (Mon–Fri 09:30–16:00 ET for US Equities / 24-7 for Crypto). |
| **SCREENER** | `data_pipeline/stock_screener.py` | TradingView Screener v3 Batch Scanner for 55 CME SSF equities (<1s refresh). |
| **DB** | `middleware/db_manager.py` | MongoDB Atlas persistence manager for real-time `account`, `positions`, `quota`, and `trades` synchronization. |
| **EE** | `execution/engine.py` | 9-Layer Execution Cadence mapping signals through state, dead-day, goals, and risk modules. |
| **OMS** | `execution/simulated_oms.py` | Risk-budget USD sizing, 6-decimal micro-crypto precision, ATR trailing stop, and VPOC/VAH/VAL take-profit snapping. |
| **AUDIT** | `core/decision_trace.py` | `DecisionTrace` diagnostic logging to `decision_trace.jsonl` for full auditability. |
| **WS** | `services/ws_server.py` | FastAPI WebSocket servers: dedicated live chart stream (`/ws/charts`) and engine telemetry gateway (`/ws/trading`) with strict schemas, dirty-check deduplication, and REST endpoints `/api/klines`, `/api/positions`, `/api/decision-traces`. |
| **UI** | `frontend/` | Stitch MCP Next.js Trading Terminal featuring Crypto Perpetuals (`/crypto`), US Futures (`/us-futures`), and Trade Logs (`/trade-logs`). |

---

## Quick Start

### Option A: Docker Deployment (Recommended for EC2 / Production)
```bash
# Build and run all services (WebSocket, backend engine, frontend, Redis)
docker compose up -d --build

# View container logs
docker compose logs -f --tail=30
```

### Option B: Local / Manual Execution

#### 1. Install dependencies
```bash
python -m venv venv
# On Windows:
.\venv\Scripts\activate
# On Linux / macOS:
source venv/bin/activate

pip install -r requirements.txt
cd frontend && npm install && cd ..
```

#### 2. Run background services
```bash
# Terminal 1 — FastAPI WebSocket Server
python services/ws_server.py

# Terminal 2 — Unified Backend Engine
python services/run_backend.py

# Terminal 3 — Next.js Institutional Trading Terminal
cd frontend && npm run dev
# Open http://localhost:3000 in your browser
```

#### 3. Run complete test suite (110 tests)
```bash
pytest tests/ -v
```

---

## Signal & Goal Telemetry Schemas

### Signal Packet Schema
```json
{
  "signal_id": "sig_98a7f62b",
  "timestamp_generated": 1698245612.482,
  "instrument": "BTC-USD",
  "direction_magnitude": 0.65,
  "confidence_score": 0.82,
  "conviction_score": 0.82,
  "regime_flag": "high_volatility",
  "flow_score": 0.21,
  "iff_veto": false,
  "latency_ms": 77
}
```

### Goal & Risk Gating Telemetry (`GOAL_UPDATE`)
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

---

## Offline Reinforcement Learning (`research/rl/`)

An offline, cost-aware Gymnasium training environment and policy suite:
- **Cost-Aware Gymnasium Env** (`research/rl/trading_env.py`): Zero-lookahead environment deciding on bar $t$ close and filling at bar $t+1$ open.
- **Unified Transaction Cost Model** (`execution/cost_model.py`): Deterministic accounting for taker/maker fees, spread, and ATR-proportional slippage shared between RL and live execution.
- **Observation Normalizer**: Fit strictly on train splits and saved to disk (`norm_stats.json`) for zero data snooping.
- **Purged Walk-Forward PPO** (`research/rl/train_rl.py`): K-fold walk-forward training with strict embargo gaps between train and validation windows.
- **Baseline Benchmarking Suite**: Evaluates Flat, Buy & Hold, Random, and Bollinger Reversion on identical validation splits with exact cost deductions.
- **Provenance & DSR**: Tracks seed dispersion (5 seeds per fold), Deflated Sharpe Ratio (DSR), Git commit hash, and configurable PASS/FAIL criteria.
- **Frozen ONNX Export & Parity** (`research/rl/export_onnx.py`): Exports SB3 PPO policies to `model.onnx` alongside `model_meta.json` containing deterministic feature-schema hashes, training config hashes, Git provenance, normalization statistics, and 1,000-sample numerical parity verification.
- **Invariants**: Guaranteed flat policy reward $\equiv 0.0$, exact cost accounting, and verified no-lookahead.


