# TRDENG Architecture & Module Change Log

**Status:** Completed & Fully Operational.
**Scope:** Documenting completed architectural additions: Goal & Risk Gating Module, Dead-Day Filter, Dynamic Leverage Curve with Stretch Penalty, RTH Market Session Gating, and the Stitch MCP Presentation Layer.

---

## 1. Completed Modules & Architectural Additions

### 1.1 `goals/goal_module.py` — Goal & Risk Gating Module
- **Monthly Trade Ceilings:** Enforces 20 Crypto Perpetuals / 80 US Equities monthly trade limits. Auto-throttles new order entries once ceilings are reached.
- **Multi-Horizon Circuit Breakers:**
  - **4.0% Daily Loss Stop:** Halts new entries if daily loss exceeds 4.0% of starting equity. Resets automatically on the next trading day.
  - **18.0% Monthly Drawdown Stop:** Halts all trading if monthly equity drawdown from peak exceeds 18.0%.
- **Atomic State Persistence:** Thread-safe, atomic tempfile writes to `quota_state.json`.

### 1.2 `data_pipeline/dead_day_filter.py` — Dead-Day & Conviction Filter
- **Chop Session Detection:** Evaluates 3 non-tradable market conditions:
  1. Range / ATR ratio $< 0.85$
  2. Relative Volume (RVOL) $< 0.70$
  3. Realized Volatility $< 0.008$ (0.8%)
- **Conviction Collapse:** When a dead day is detected, `effective_conviction` collapses to $0.0$, rejecting low-EV trades before capital is committed.

### 1.3 Dynamic Leverage Curve with ATR Stretch Penalty
- Computes position leverage dynamically:
  $$\text{Leverage} = \text{MIN\_LEV} + (\text{MAX\_LEV} - \text{MIN\_LEV}) \times \text{effective\_conviction} \times \frac{1}{\max(1.0, \frac{\text{range\_atr\_ratio}}{1.2})}$$
  - **Crypto Perpetuals:** $1.0\times - 5.0\times$
  - **US Stock Futures:** $1.0\times - 10.0\times$
- **Stretch Penalty:** Dampens leverage when price range extends beyond 1.2x ATR.

### 1.4 `execution/market_session.py` — Regular Trading Hours (RTH) Gating
- Enforces strict Regular Trading Hours (09:30–16:00 ET Mon–Fri) for US Equities and Stock Futures.
- Permits continuous 24/7/365 trading for Crypto Perpetuals.

### 1.5 Stitch MCP Institutional Frontend Architecture
- **Stitch MCP UI Design** (`projects/15624410236763381846`):
  - **`/crypto`** (Default `/`): 24/7 Funding Heatmap, Liquidation Safety Cushion, VPOC/CVD Microstructure, L2 DOM Depth, Active Crypto Positions.
  - **`/us-futures`**: RTH Session Status Banner, 7-Day Screener Top Candidate Pool (Long/Short), Single Stock Futures Metrics, Active Stock Positions.
  - **`/trade-logs`**: Ceilings Progress, 4% Daily / 18% Monthly Circuit Breaker Telemetry, Asset-Filtered Audit Logs.

### 1.6 Decoupling & Predictability Hardening Pass
- **Consolidated Symbol State:** Centralized state tracking in `core/symbol_state.py` via the `SymbolStateRegistry` singleton to safely share historical bars across multiple module layers (Dead-Day Filter, IFF Gate).
- **Defined Pipeline Cadence:** `ExecutionEngine` now orchestrates a 9-layer decision matrix from DP feature ingestion down to Goal/Risk module overrides, bringing full lifecycle predictability.
- **Decision Tracing:** Fully auditable `DecisionTrace` dataclass records the state of every gate in real-time, streaming out to `decision_trace.jsonl` and `/api/decision-traces`.
- **Non-blocking Micro-Buffer:** Replaced synchronous `time.sleep(hold)` with `hold_and_evaluate_micro_buffer` async tick preemption in `alpha_overlay/iff.py`.

### 1.7 Paper Trading Precision, Dynamic Pricing & Persistence Hardening (Latest)
- **Position Precision & Micro-Crypto Sizing:** Upgraded `SimulatedFuturesOMS` from 4 to 6 decimal precision for crypto instruments (`1e-6` cutoff), ensuring fractional BTC/ETH allocations (e.g. `0.006002 BTC`) preserve accurate satoshi quantities instead of truncating to `0.0`.
- **MongoDB Atlas Bidirectional Sync:** Upgraded `MongoDatabaseManager` in `middleware/db_manager.py` with automatic cross-referencing between `primary_account["positions"]` and the `positions` collection. Guarantees real signed quantities (`qty`), mark prices, and unrealized P&L persist continuously.
- **Dynamic Price Feed Streaming:** Integrated live crypto prices via Binance API and US equities via TradingView Screener in `services/ws_server.py`. Added `@app.get("/api/klines")` endpoint for instant TradingView chart hydration.
- **TradingView Screener v3 Batch Scanning:** Migrated `data_pipeline/stock_screener.py` to `tradingview_screener` v3 batch API, scanning all 55 CME SSF equities in a single call (<1s) and populating `screener_cache.json`.
- **Docker Production Compose:** Hardened root `docker-compose.yml` with proper service mappings for unified deployment on Amazon EC2.

---

## 2. Updated File Registry

| File | Status | Description |
|---|---|---|
| `goals/goal_module.py` | NEW | Goal & Risk Gating Module (Ceilings, Breakers, Dynamic Leverage). |
| `data_pipeline/dead_day_filter.py` | NEW | Dead-Day & Conviction Filter. |
| `data_pipeline/stock_screener.py` | UPDATED | TradingView Screener v3 Batch Scanner for 55 CME SSF equities. |
| `middleware/db_manager.py` | UPDATED | MongoDB Atlas persistence with automatic account & positions cross-referencing. |
| `middleware/event_bus.py` | UPDATED | Schema-compliant event publishing with `qty`, `size`, `instrument`, and `current_price`. |
| `execution/market_session.py` | NEW | Centralized RTH Session Gating. |
| `execution/quota_manager.py` | REFACTORED | Compatibility adapter delegating to `GoalModule`. |
| `execution/engine.py` | UPDATED | Sizes proposed orders using `GoalModule.evaluate_trade()`. |
| `execution/simulated_oms.py` | UPDATED | Dynamic leverage, 6-decimal micro-crypto precision, and $10 risk budget execution. |
| `services/ws_server.py` | UPDATED | Dynamic price feeds (Binance + TV), `/api/klines`, and real-time 5-second candle aggregation. |
| `docker-compose.yml` | UPDATED | Multi-container Docker deployment for EC2 / production. |
| `frontend/components/charts/TradingViewChart.tsx` | UPDATED | TradingView Lightweight Chart with real-time ticks and REST fallback hydration. |
| `frontend/components/terminal/` | NEW | Stitch MCP Terminal components (`CryptoTerminal`, `UsFuturesTerminal`, `TradeLogsTerminal`). |
| `frontend/components/navigation/` | NEW | `StitchHeader` & `StitchSidebar` navigation components. |

---

## 3. Verification & Test Suite
- All 110 Python unit tests in `tests/` pass 100% (`pytest tests/`).
- Next.js production build (`npm run build`) and dev server compile cleanly (`200 OK`).