# TRDENG — Patch Set: Risk Budget & Dead-Day Filter

**Status:** Ready to apply
**Scope:** 2 of 3 proposed fixes. Veto-gate buffer (#3) is **blocked** pending `execution/engine.py` — see note at bottom.

---

## Patch 1 — Risk Budget: bind to live equity, not a frozen constant

**File:** `goals/goal_module.py`
**Root cause:** `position_risk_budget_usd()` sizes off `TOTAL_CAPITAL_USD = 1000.0`, a module-level constant that never updates. Actual live equity (`GoalState.equity_current_usd`) already moves with every closed trade via `record_trade_result()`, but risk sizing never reads it. Result: risk budget stays pinned to the day-1 capital figure regardless of compounding or drawdown.

### Diff

```diff
 def position_risk_budget_usd(
     asset_class: AssetClass,
+    state: Optional[GoalState] = None,
 ) -> float:
     """Dollar amount you're willing to lose on a single trade if the stop is hit."""
     ac: AssetClass = "crypto" if asset_class.lower() == "crypto" else "stock"
     cfg = CONFIG[ac]
-    allocated_capital = TOTAL_CAPITAL_USD * (cfg.capital_allocation_pct / 100.0)
+    state = state or load_state()
+    allocated_capital = state.equity_current_usd * (cfg.capital_allocation_pct / 100.0)
     return round(allocated_capital * (cfg.risk_per_trade_pct / 100.0), 2)
```

### Call-site update in `evaluate_trade()`

```diff
     leverage = select_leverage(ac, effective_conviction, range_atr_ratio)
-    risk_budget = position_risk_budget_usd(ac)
+    risk_budget = position_risk_budget_usd(ac, state)
```

`state` is already loaded and in scope at this point in `evaluate_trade()`, so this is a pure plumbing change — no new I/O.

### Optional safety clamp (recommended)

Without a floor/ceiling, a large drawdown could shrink `equity_current_usd` enough to make `risk_budget` trivially small (can't size a meaningful trade), and a strong run-up could make a single trade's dollar risk grow faster than intended. Add bounds pulled from `CONFIG`:

```diff
     state = state or load_state()
     allocated_capital = state.equity_current_usd * (cfg.capital_allocation_pct / 100.0)
-    return round(allocated_capital * (cfg.risk_per_trade_pct / 100.0), 2)
+    raw_budget = allocated_capital * (cfg.risk_per_trade_pct / 100.0)
+    return round(max(1.0, min(raw_budget, TOTAL_CAPITAL_USD * 0.05)), 2)
```

(`min $1`, `max 5% of original capital base` — tune both to taste; the point is bounding the tail cases, not the specific numbers.)

### Why this is safe to ship
- No change to `CONFIG` shapes, `TradeDecision`, or any external API contract.
- `state` is already threaded through every other check in `evaluate_trade()` — this just adds one more consumer of it.
- `TOTAL_CAPITAL_USD` stays as-is; it's still used correctly elsewhere (e.g., as the denominator for `daily_loss_pct` and `monthly_progress_summary`'s target calc) where a fixed base capital reference is actually appropriate. Only the *risk budget* calc was the bug.

---

## Patch 2 — Dead-Day Filter: rolling percentile instead of fixed constants

**File:** `data_pipeline/dead_day_filter.py`
**Root cause:** `cond_a`, `cond_b`, `cond_c` compare `range_atr_ratio`, `rvol`, and `realized_vol` against fixed constants (`0.60`, `0.65`, `0.75`, `0.70`, and a vol threshold of `0.025`/`0.009`). These drift out of calibration as the market's baseline volatility regime shifts over months/years.

### Design
- Maintain a rolling history buffer (252 sessions) per symbol of `range_atr_ratio`, `rvol`, and `realized_vol`.
- Replace each fixed constant with a percentile rank against that symbol's own trailing distribution.
- Cold-start fallback: until 60+ historical points exist, fall back to the current fixed constants (avoids a meaningless percentile off a near-empty sample).

### Diff

```diff
 from __future__ import annotations
 import numpy as np
 import pandas as pd
+from collections import deque
+
+_HISTORY_LEN = 252
+_MIN_HISTORY = 60  # cold-start floor before percentile logic activates
+_history: dict[str, deque] = {}  # symbol -> deque of (range_atr_ratio, rvol, realized_vol)
+
+
+def _get_percentile_thresholds(symbol: str) -> dict | None:
+    """Returns rolling 10th-percentile thresholds for this symbol, or None if not enough history."""
+    buf = _history.get(symbol)
+    if buf is None or len(buf) < _MIN_HISTORY:
+        return None
+    arr = np.array(buf)
+    return {
+        "range_atr_p10": float(np.percentile(arr[:, 0], 10)),
+        "rvol_p10": float(np.percentile(arr[:, 1], 10)),
+        "vol_p10": float(np.percentile(arr[:, 2], 10)),
+    }
+
+
+def _update_history(symbol: str, range_atr_ratio: float, rvol: float, realized_vol: float) -> None:
+    buf = _history.setdefault(symbol, deque(maxlen=_HISTORY_LEN))
+    buf.append((range_atr_ratio, rvol, realized_vol))


 def compute_dead_day_and_conviction(
     df: pd.DataFrame,
     ml_confidence: float,
     s_flow: float = 0.0,
     s_composite_dir: float = 0.0,
-    is_crypto: bool = False
+    is_crypto: bool = False,
+    symbol: str = "DEFAULT",
 ) -> dict:
     ...
     log_ret = np.log(df["Close"] / df["Close"].shift(1))
     realized_vol = float(np.sqrt(log_ret.ewm(span=min(5, len(df)), adjust=False).var() * 252).iloc[-1])

-    # Dead-Day Filter Rules
-    vol_thresh = 0.025 if is_crypto else 0.009
-    cond_a = range_atr_ratio < 0.60
-    cond_b = (rvol < 0.65) and (range_atr_ratio < 0.75)
-    cond_c = (realized_vol < vol_thresh) and (range_atr_ratio < 0.70)
-    is_dead_day = bool(cond_a or cond_b or cond_c)
+    # Dead-Day Filter Rules — rolling 10th-percentile, fixed-constant cold-start fallback
+    _update_history(symbol, range_atr_ratio, rvol, realized_vol)
+    pct = _get_percentile_thresholds(symbol)
+
+    if pct is not None:
+        range_atr_thresh_a = pct["range_atr_p10"]
+        range_atr_thresh_b = pct["range_atr_p10"] * 1.25   # keeps cond_b/c relatively looser than cond_a, matching original spacing (0.60 -> 0.75 -> 0.70)
+        range_atr_thresh_c = pct["range_atr_p10"] * 1.17
+        rvol_thresh = pct["rvol_p10"]
+        vol_thresh = pct["vol_p10"]
+    else:
+        range_atr_thresh_a, range_atr_thresh_b, range_atr_thresh_c = 0.60, 0.75, 0.70
+        rvol_thresh = 0.65
+        vol_thresh = 0.025 if is_crypto else 0.009
+
+    cond_a = range_atr_ratio < range_atr_thresh_a
+    cond_b = (rvol < rvol_thresh) and (range_atr_ratio < range_atr_thresh_b)
+    cond_c = (realized_vol < vol_thresh) and (range_atr_ratio < range_atr_thresh_c)
+    is_dead_day = bool(cond_a or cond_b or cond_c)
```

### Notes / open decisions
- **`_history` is in-memory and per-process.** It resets on restart, which re-triggers the cold-start fallback each time the service restarts. If TRDENG restarts frequently, persist this buffer (e.g., append to a small parquet/JSON file per symbol) rather than rebuilding from scratch each run.
- **The `1.25` / `1.17` multipliers** are a direct translation of the original ratio between `0.60`, `0.75`, `0.70` (i.e. preserving the original spacing between the three conditions) — not independently tuned. Worth validating against a backtest before trusting them at face value.
- **`is_crypto` param is now redundant** once percentile mode is active (the rolling history is already asset/symbol-specific), but it's kept for the cold-start fallback path, which still needs the old crypto/stock split.
- **Call-site change required:** every caller of `compute_dead_day_and_conviction()` needs to start passing `symbol=` for the history buffer to key correctly. Grep for existing call sites (likely in `execution/engine.py`) before shipping.

---

## Blocked — Patch 3: Veto-gate timing buffer

**Not drafted.** Reading `alpha_overlay/iff.py`, `apply_iff_gate()` is a single synchronous call — `s_composite` and `flow_score` aren't two independently-timed async streams racing each other; `get_flow_score()` completes inline before the veto comparison. There's no async hold-queue to add *in this file*.

The real question is how stale `s_composite` is **before** it reaches this function — that's determined by `execution/engine.py`, which hasn't been shared. Please upload it (or the relevant call path from Meta-Aggregator output → `apply_iff_gate()` call) so the actual latency gap, if any, can be verified before a fix is proposed.
