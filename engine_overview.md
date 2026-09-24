# TRDENG Architecture Overview

TRDENG is a hardened, production-grade algorithmic trading engine designed for end-to-end capital safety, isolated multi-strategy execution, and exchange reconciliation.

Below is a brief overview of the engine's layers, inputs, outputs, and the signal mechanism.

## 1. Market Data & Feature Engine
**Purpose:** Ingests raw market data and computes deterministic features.
*   **Inputs:** Live market data feeds (e.g., Binance WebSocket `aggTrade`, Alpaca Equities REST).
*   **Process:** Standardizes incoming ticks and bars.
*   **Outputs:** Standardized data frames and deterministic technical features via a pinned feature engine (`feature_standardizer.py`) to prevent train/serve skew.

## 2. Strategy Sleeves (Signal Generation)
**Purpose:** Independent strategies running in isolated capital sleeves to prevent signal cancellation (e.g., Trend vs. Mean Reversion).
*   **Inputs:** Standardized market features, `PositionContext` (current position size, entry price, open duration, unrealized PnL).
*   **Process:** Evaluates market conditions within a strict 30ms watchdog timeout per strategy. 
*   **Outputs:** A rich `OrderIntent` contract (not just a basic float direction).

## 3. Signal Mechanism & Validation (`OrderIntent`)
**Purpose:** Defines and validates the exact intent of the strategy before execution.
*   **Inputs:** The generated `OrderIntent` from the strategy sleeve.
*   **Process:** 
    *   **Strict Validation:** Ensures no NaN/Inf, prices > 0, valid TTL (time-to-live), and correct schema.
    *   **Regime Selection:** A Meta-Aggregator acts as a selector to mute incompatible strategy sleeves based on the current market regime.
*   **Outputs:** Validated `OrderIntent` (contains intent type like `ENTRY`/`EXIT`/`SCALE`, multi-leg support, and stop-loss/take-profit prices).

## 4. Hardened Risk Guard
**Purpose:** Provides absolute capital safety and strictly limits exposure.
*   **Inputs:** Validated `OrderIntent`, overall portfolio equity (Realized + Unrealized Mark-to-Market).
*   **Process:** 
    *   Checks multi-horizon drawdowns and max position size limits.
    *   Applies an emergency kill switch (`EMERGENCY_HALT`) if limits are breached.
*   **Outputs:** Approved orders passed to the execution router, or halted execution if risk caps are hit.

## 5. Execution Core & Reconciliation
**Purpose:** Reliably executes orders on the exchange with state management and idempotency.
*   **Inputs:** Approved, risk-checked orders.
*   **Process:**
    *   **Idempotency & Rate Limiting:** Generates deterministic Client Order IDs (`clOrdId`) and applies leaky-bucket rate limiting to prevent API bans.
    *   **State Machine:** Explicit states (`PENDING_SUBMIT`, `FILLED`, `REJECTED`, etc.).
    *   **Capital Protection:** Places exchange-side native `STOP_MARKET` orders immediately upon fill.
    *   **Reconciliation:** Queries the exchange on boot or reconnect to verify actual positions versus local memory.
*   **Outputs:** Actual market executions, state updates to Telemetry and Database.

## 6. Telemetry & Persistence
**Purpose:** Real-time monitoring and historical record keeping.
*   **Inputs:** Order execution states, PnL updates, system health metrics.
*   **Outputs:** Fast WebSocket gateway (`/ws/trading`) for the UI, and asynchronous batch writes to the database (MongoDB/SQLite).
