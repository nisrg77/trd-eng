"""
goals/goal_module.py — Simplified Goal & Risk Gating Module

Active Rules:
  1. 80/20 Daily Trade Rule: Crypto strictly capped at 20 trades/day, Stocks at 80 trades/day.
  2. Total Capital Depletion Stop: If the $1000 capital is completely finished (total PnL <= -$1000.0), system stops.
  (All other execution gates are disabled).
"""

from __future__ import annotations

import json
import os
import sys
import tempfile
import logging
from dataclasses import dataclass, field, asdict
from datetime import date
from typing import Literal, Optional

log = logging.getLogger(__name__)

AssetClass = Literal["crypto", "stock"]
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE_DIR, "quota_state.json")

# ---------------------------------------------------------------------------
# Simplified Constraints
# ---------------------------------------------------------------------------
MAX_MONTHLY_LOSS_USD = -1000.0
DAILY_TRADE_LIMITS = {"crypto": 20, "stock": 80}

# Fallback floor leverage (only used if conviction data unavailable)
STATIC_LEVERAGE = 1.0
STATIC_RISK_BUDGET = 10.0

# Backward compatibility / legacy config references
CONFIG = {
    "crypto": type("Config", (), {"monthly_trade_ceiling": 20, "daily_trade_limit": 20})(),
    "stock": type("Config", (), {"monthly_trade_ceiling": 80, "daily_trade_limit": 80})(),
}
TOTAL_CAPITAL_USD = 1000.0

# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------
@dataclass
class BucketState:
    trades_today: int = 0
    realized_pnl_this_month_usd: float = 0.0
    last_reset_day: str = field(default_factory=lambda: date.today().isoformat())
    last_reset_month: str = field(default_factory=lambda: date.today().strftime("%Y-%m"))


@dataclass
class GoalState:
    crypto: BucketState = field(default_factory=BucketState)
    stock: BucketState = field(default_factory=BucketState)
    engine_paused: bool = False

    def bucket(self, asset_class: AssetClass) -> BucketState:
        ac = "crypto" if str(asset_class).lower() == "crypto" else "stock"
        return self.crypto if ac == "crypto" else self.stock


class GoalModule:
    INITIAL_STATE = {
        "crypto": {"trades_today": 0, "realized_pnl_this_month_usd": 0.0, "completed": 0},
        "stock": {"trades_today": 0, "realized_pnl_this_month_usd": 0.0, "completed": 0},
        "futures": {"trades_today": 0, "realized_pnl_this_month_usd": 0.0, "completed": 0},
        "engine_paused": False,
    }


def _atomic_write(path: str, data: dict) -> None:
    dir_ = os.path.dirname(os.path.abspath(path)) or "."
    fd, tmp_path = tempfile.mkstemp(dir=dir_)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, default=str)
        os.replace(tmp_path, path)
    except Exception:
        if os.path.exists(tmp_path):
            os.remove(tmp_path)
        raise


def load_state(path: str = STATE_PATH) -> GoalState:
    if not os.path.exists(path):
        return GoalState()
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        
        crypto_raw = raw.get("crypto", {})
        stock_raw = raw.get("stock", raw.get("futures", {}))
        
        state = GoalState(
            crypto=BucketState(**{k: v for k, v in crypto_raw.items() if k in BucketState.__annotations__}),
            stock=BucketState(**{k: v for k, v in stock_raw.items() if k in BucketState.__annotations__}),
            engine_paused=bool(raw.get("engine_paused", False))
        )
        _roll_periods(state)
        return state
    except Exception as e:
        log.warning(f"Error loading goal state: {e}. Returning fresh state.")
        return GoalState()


def save_state(state: GoalState, path: str = STATE_PATH) -> None:
    data = {
        "crypto": asdict(state.crypto),
        "stock": asdict(state.stock),
        "futures": asdict(state.stock),
        "engine_paused": state.engine_paused
    }
    data["crypto"]["completed"] = state.crypto.trades_today
    data["stock"]["completed"] = state.stock.trades_today
    data["futures"]["completed"] = state.stock.trades_today
    _atomic_write(path, data)


def _roll_periods(state: GoalState) -> None:
    """Reset daily/monthly counters when the calendar rolls over."""
    today_str = date.today().isoformat()
    month_str = date.today().strftime("%Y-%m")
    
    for bucket in (state.crypto, state.stock):
        if bucket.last_reset_day != today_str:
            bucket.trades_today = 0
            bucket.last_reset_day = today_str
        if bucket.last_reset_month != month_str:
            bucket.realized_pnl_this_month_usd = 0.0
            bucket.last_reset_month = month_str


# ---------------------------------------------------------------------------
# Core gate
# ---------------------------------------------------------------------------
@dataclass
class TradeDecision:
    allowed: bool
    reason: str
    leverage: float = STATIC_LEVERAGE
    risk_budget_usd: float = STATIC_RISK_BUDGET


def evaluate_trade(
    asset_class: str,
    dead_day_result: dict,
    state: Optional[GoalState] = None,
    persist: bool = True,
) -> TradeDecision:
    ac: AssetClass = "crypto" if asset_class.lower() == "crypto" else "stock"
    state = state or load_state()
    _roll_periods(state)
    bucket = state.bucket(ac)

    # 1. Total $1000 capital finished check — system stops completely when capital is exhausted
    total_realized_pnl = state.crypto.realized_pnl_this_month_usd + state.stock.realized_pnl_this_month_usd
    if total_realized_pnl <= -TOTAL_CAPITAL_USD:
        state.engine_paused = True
        if persist:
            save_state(state)
        return TradeDecision(False, f"Engine stopped: $1000 total capital finished (PnL: ${total_realized_pnl:.2f})")

    # If capital has not been finished (PnL > -1000), unpause engine if it was paused
    if state.engine_paused:
        if total_realized_pnl > -TOTAL_CAPITAL_USD:
            state.engine_paused = False
            if persist:
                save_state(state)
        else:
            return TradeDecision(False, "Engine stopped: $1000 total capital finished.")

    # 2. Daily 80/20 trade limit rule (20 crypto / 80 stock per day)
    limit = DAILY_TRADE_LIMITS[ac]
    if bucket.trades_today >= limit:
        return TradeDecision(False, f"{ac} daily trade limit reached ({bucket.trades_today}/{limit})")

    # NOTE: All other execution gates (dead-day filter, zero conviction gate, etc.)
    # are DISABLED per user specification. Only the 80/20 daily trade rule and $1000
    # capital depletion stop remain active.

    # 3. Approved — calculate dynamic leverage
    effective_conviction = (
        float(dead_day_result.get("effective_conviction", 1.0))
        if isinstance(dead_day_result, dict)
        else 1.0
    )
    range_atr_ratio = (
        float(dead_day_result.get("range_atr_ratio", 1.0))
        if isinstance(dead_day_result, dict)
        else 1.0
    )
    dyn_leverage = select_leverage(ac, effective_conviction, range_atr_ratio)
    return TradeDecision(True, "OK", leverage=dyn_leverage)


def record_trade_result(
    asset_class: str,
    pnl_usd: float,
    state: Optional[GoalState] = None,
    persist: bool = True,
) -> GoalState:
    """Call after a trade closes to update counters."""
    ac: AssetClass = "crypto" if asset_class.lower() == "crypto" else "stock"
    state = state or load_state()
    _roll_periods(state)
    bucket = state.bucket(ac)

    bucket.trades_today += 1
    bucket.realized_pnl_this_month_usd += pnl_usd

    total_pnl = state.crypto.realized_pnl_this_month_usd + state.stock.realized_pnl_this_month_usd
    if total_pnl <= -TOTAL_CAPITAL_USD:
        state.engine_paused = True
        log.critical(
            f"[GoalModule] TOTAL $1000 CAPITAL FINISHED (Total PnL: ${total_pnl:+.2f}). SYSTEM STOPPED."
        )

    log.info(
        f"[GoalModule] {ac.upper()} Trade Closed (P/L: ${pnl_usd:+.2f}). "
        f"Daily Trades: {bucket.trades_today}/{DAILY_TRADE_LIMITS[ac]}, "
        f"Month P/L: ${bucket.realized_pnl_this_month_usd:+.2f}, Total P/L: ${total_pnl:+.2f}"
    )

    if persist:
        save_state(state)
    return state


def select_leverage(
    asset_class: str,
    effective_conviction: float = 1.0,
    range_atr_ratio: float = 1.0,
) -> float:
    """
    Dynamic leverage curve decided by the engine based on conviction.
    - Crypto: 1x – 5x  (higher leverage, 24/7 market)
    - Stocks: 1x – 3x  (lower leverage, RTH only)
    Scaled linearly by effective_conviction [0, 1].
    ATR ratio > 1.5 (wide range / high vol day) reduces leverage by 30%.
    """
    ac = asset_class.lower()
    conv = max(0.0, min(1.0, float(effective_conviction)))

    if ac == "crypto":
        max_lev = 5.0
        min_lev = 1.0
    else:  # stock / futures
        max_lev = 3.0
        min_lev = 1.0

    lev = min_lev + (max_lev - min_lev) * conv

    # Reduce leverage on wide ATR range days (choppy market)
    if float(range_atr_ratio) > 1.5:
        lev *= 0.7

    return round(max(min_lev, min(max_lev, lev)), 2)


def position_risk_budget_usd(
    asset_class: str,
    state: Optional[GoalState] = None,
) -> float:
    return STATIC_RISK_BUDGET


def monthly_progress_summary(state: Optional[GoalState] = None) -> dict:
    state = state or load_state()
    total_pnl = state.crypto.realized_pnl_this_month_usd + state.stock.realized_pnl_this_month_usd
    return {
        "monthly_target_usd": 100.0,
        "monthly_pnl_usd": round(total_pnl, 2),
        "monthly_pnl_pct": round(total_pnl / TOTAL_CAPITAL_USD * 100.0, 2),
        "crypto_trades_used": f"{state.crypto.trades_today}/{DAILY_TRADE_LIMITS['crypto']}",
        "stock_trades_used": f"{state.stock.trades_today}/{DAILY_TRADE_LIMITS['stock']}",
        "crypto_completed": state.crypto.trades_today,
        "crypto_ceiling": DAILY_TRADE_LIMITS["crypto"],
        "stock_completed": state.stock.trades_today,
        "stock_ceiling": DAILY_TRADE_LIMITS["stock"],
        "engine_paused": state.engine_paused,
    }


# Self-reference for callers using `from goals.goal_module import goal_module`
goal_module = sys.modules[__name__]
