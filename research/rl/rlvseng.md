# Architecture Comparison: TRDENG Core Engine vs. RL Subsystem

This document provides a detailed comparison between **TRDENG (the Core Quantitative Engine)** and the **Reinforcement Learning (RL) Subsystem (`research/rl/`)**, detailing their design paradigms, execution authorities, risk controls, and how they interact.

---

## 1. High-Level Architecture

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                                  TRDENG CORE ENGINE                                    │
│                        (Operating System & Live Execution Cage)                        │
│                                                                                        │
│   Incoming Ticks ──► Preprocessor ──► Strategy Registry ──► 9 Risk Gates ──► Live OMS  │
│                                              │                                         │
│                                              ▼                                         │
│   ┌────────────────────────────────────────────────────────────────────────────────┐   │
│   │                          RL SUBSYSTEM (SHADOW AGENT)                           │   │
│   │                       (Offline Learning & Shadow Policy)                       │   │
│   │                                                                                │   │
│   │   12-dim Feature Vector ──► Frozen ONNX Actor ──► Action {-1, 0, +1}           │   │
│   │                                    │                                           │   │
│   │                                    ▼                                           │   │
│   │                       Logged in Shadow Mode (tag: "rl_shadow")                 │   │
│   │                       * ZERO Live Orders Sent to Exchanges *                   │   │
│   └────────────────────────────────────────────────────────────────────────────────┘   │
└────────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. Core Differences Matrix

| Dimension | TRDENG Core Engine | RL Subsystem (`research/rl/`) |
| :--- | :--- | :--- |
| **Paradigm** | **Deterministic & Rule-Based** | **Statistical Machine Learning / Neural Policy** |
| **Signal Logic** | Explicit mathematical conditions (e.g. *If RSI < 30 and Price crosses lower Bollinger Band, Buy*). | Learned non-linear state mapping: a 12-dimensional vector $\mathbf{s}_t$ is evaluated by a deep actor network. |
| **Execution Authority** | **Live Execution**: Connected to real brokers, demo trading APIs, exchange routers, and sleeve managers. | **Shadow Mode Only**: Returns `None` on live calls; logs signals to `decision_trace.jsonl` with zero broker access. |
| **Risk & Position Sizing** | Hard institutional gates (kill switch, leverage caps, daily loss limit, dead-day filter, LOB imbalance). | Internal optimization objective: reward function penalizes turnover, slippage, and drawdown. |
| **Adaptation & Retraining**| Strategy parameters are static until explicitly re-tuned with Optuna and promoted via governance. | Trains across thousands of historical episodes with walk-forward purged splits and Deflated Sharpe Ratio (DSR) gates. |
| **Runtime Isolation** | Standard Python quant stack (`pandas`, `numpy`, `ccxt`, `fastapi`). | Live runtime imports **`onnxruntime` and `numpy` only**. Heavy training tools (`torch`, `stable-baselines3`, `gymnasium`) are strictly isolated offline. |
| **Latency Benchmark** | Guarded by the `StrategyValidator` 30 ms watchdog. | Sub-millisecond CPU inference (<0.2 ms per evaluation) using frozen ONNX runtime. |

---

## 3. Detailed Component Breakdown

### A. TRDENG Core Engine (The "Safety Cage" & Operating System)
1. **Data Ingestion & Invariants**:
   - Ingests tick and candle data across crypto and traditional asset classes.
   - Cleanses, calculates ATR/RSI/Bollinger indicators, and applies dead-day filtering.
2. **Strategy Registry & Sleeves**:
   - Manages plug-and-play strategies (Bollinger Pattern, Heikin-Ashi SAR, Pair Cointegration, Dual Thrust).
   - Enforces capital sleeve limits and portfolio allocation percentages.
3. **Institutional Risk Gates**:
   - Intercepts all order intents before they can reach the exchange.
   - Blocks trades on excessive daily loss, monthly drawdown, or LOB toxicity.
4. **Order Management System (OMS)**:
   - Manages state, demo trading APIs, live CCXT routers, trailing ATR stops, and partial take-profits.

---

### B. RL Subsystem (The "Experimental Intelligence Layer")
1. **Offline Training Sandbox (`research/rl/trading_env.py`)**:
   - Cost-aware Gymnasium environment modeling 4 bps taker fees, 2 bps spread, and ATR-based slippage.
   - Zero lookahead: decisions made at bar $t$ close are filled at bar $t+1$ open.
2. **Purged Walk-Forward Training (`research/rl/train_rl.py`)**:
   - Trains multi-seed PPO policies across purged folds with embargo gaps to eliminate data leakage.
   - Benchmarks policies against 8 standard and quantitative baselines (Dual Thrust, Awesome Oscillator, Heikin-Ashi, RSI Pattern).
3. **Frozen ONNX Export (`research/rl/export_onnx.py`)**:
   - Exports the trained PyTorch actor into a standalone `model.onnx` file with dynamic batching.
   - Produces `model_meta.json` embedding a 16-character SHA-256 schema hash to guarantee input alignment.
4. **Live Shadow Plugin (`strategies/ai/onnx_policy_plugin.py`)**:
   - Runs in parallel with rule-based strategies inside the live loop.
   - Reconstructs the 12-dim causal state, executes ONNX inference in <0.2 ms, and logs hypothetical fills.
   - `ShadowPnLTracker` tracks simulated equity and drawdown without risking real funds.
5. **Staged Governance (`middleware/strategy_promotion.py`)**:
   - Starts strictly in `RESEARCH` stage.
   - Advance to `PAPER_SOAK` requires $\ge 30$ shadow trades, $\ge 7$ days, max drawdown $\le 8\%$, and explicit human cryptographic approval.

---

## 4. How TRDENG and RL Interact Harmoniously

1. **Engine Feeds State to RL**: TRDENG standardizes live candles and passes them to `ONNXPolicyPlugin._build_observation()`.
2. **RL Evaluates Without Risk**: The policy generates action probabilities and logs shadow decisions to `decision_trace.jsonl`.
3. **Engine Prevents Rogue Execution**: Because `shadow_mode=True` is enforced, the RL plugin returns `None` to the engine router, preventing unintended live orders.
4. **Promotion Path**: Only after an RL policy passes all out-of-sample shadow soak criteria can a human manager promote it to active paper execution.
