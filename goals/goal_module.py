"""
goals/goal_module.py — Goal & Risk Gating Module for TRDENG

Wraps around brain/meta_aggregator.py + alpha_overlay/iff.py output
(specifically the dict returned by compute_dead_day_and_conviction())
and decides, per candidate trade:

  1. Is this asset class's monthly trade ceiling already hit?
  2. Is today a dead day? (uses is_dead_day from dead-day filter)
  3. Has a circuit breaker (daily loss / monthly drawdown) fired?
  4. If all clear -> what leverage should this trade use?
     (derived from effective_conviction + range_atr_ratio, never a flat default)

State persists to quota_state.json using atomic tempfile writes,
so it survives restarts and is broadcast to the Next.js dashboard.
"""

from __future__ import annotations

import json
import os
import tempfile
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, date
from typing import Literal, Optional

log = logging.getLogger(__name__)

AssetClass = Literal["crypto", "stock"]

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_PATH = os.path.join(BASE_DIR, "quota_state.json")

import sys
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)
import config



# ---------------------------------------------------------------------------
# Config — tune these; nothing here is a "daily return target"
# ---------------------------------------------------------------------------

@dataclass
class AssetClassConfig:
    monthly_trade_ceiling: int
    max_leverage: float
    risk_per_trade_pct: float              # % of capital risked per trade (stop-loss distance basis)
    daily_loss_circuit_breaker_pct: float  # % of capital, halts new entries for rest of day
    capital_allocation_pct: float          # % of the $1000 pool assigned to this bucket


CONFIG: dict[AssetClass, AssetClassConfig] = {
    "crypto": AssetClassConfig(
        monthly_trade_ceiling=20,
        max_leverage=5.0,
        risk_per_trade_pct=1.25,
        daily_loss_circuit_breaker_pct=4.0,
        capital_allocation_pct=30.0,
    ),
    "stock": AssetClassConfig(
        monthly_trade_ceiling=80,
        max_leverage=10.0,
        risk_per_trade_pct=0.75,
        daily_loss_circuit_breaker_pct=4.0,
        capital_allocation_pct=70.0,
    ),
}

TOTAL_CAPITAL_USD = 1000.0
MONTHLY_DRAWDOWN_PAUSE_PCT = 18.0   # of TOTAL_CAPITAL_USD, pauses entire engine
MONTHLY_TARGET_PCT = 10.0          # informational only — never gates a trade

# Leverage curve shaping
MIN_LEVERAGE = 1.0
LEVERAGE_CONVICTION_EXPONENT = 1.0   # >1.0 makes leverage more conservative at low conviction


# ---------------------------------------------------------------------------
# State
# ---------------------------------------------------------------------------

@dataclass
class BucketState:
    trades_this_month: int = 0
    wins: int = 0
    losses: int = 0
    win_pnl: float = 0.0
    loss_pnl: float = 0.0
    realized_pnl_this_month_usd: float = 0.0
    realized_pnl_today_usd: float = 0.0
    last_reset_month: str = field(default_factory=lambda: date.today().strftime("%Y-%m"))
    last_reset_day: str = field(default_factory=lambda: date.today().isoformat())


@dataclass
class GoalState:
    crypto: BucketState = field(default_factory=BucketState)
    stock: BucketState = field(default_factory=BucketState)
    equity_peak_usd: float = TOTAL_CAPITAL_USD
    equity_current_usd: float = TOTAL_CAPITAL_USD
    engine_paused: bool = False
    pause_reason: Optional[str] = None

    def bucket(self, asset_class: AssetClass) -> BucketState:
        # Normalize 'futures' or 'stocks' to 'stock'
        ac = "crypto" if asset_class.lower() == "crypto" else "stock"
        return self.crypto if ac == "crypto" else self.stock


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
        state = GoalState()
        save_state(state, path)
        return state
    try:
        with open(path, "r", encoding="utf-8") as f:
            raw = json.load(f)
        
        # Handle legacy quota_state.json mapping if present
        crypto_raw = raw.get("crypto", {})
        stock_raw = raw.get("stock", raw.get("futures", {}))
        
        state = GoalState(
            crypto=BucketState(**{k: v for k, v in crypto_raw.items() if k in BucketState.__annotations__}),
            stock=BucketState(**{k: v for k, v in stock_raw.items() if k in BucketState.__annotations__}),
            equity_peak_usd=float(raw.get("equity_peak_usd", TOTAL_CAPITAL_USD)),
            equity_current_usd=float(raw.get("equity_current_usd", TOTAL_CAPITAL_USD)),
            engine_paused=bool(raw.get("engine_paused", False)),
            pause_reason=raw.get("pause_reason"),
        )
        _roll_periods(state)
        return state
    except Exception as e:
        log.warning(f"Error loading goal state from {path}: {e}. Initializing fresh state.")
        state = GoalState()
        save_state(state, path)
        return state


def save_state(state: GoalState, path: str = STATE_PATH) -> None:
    data = {
        "crypto": asdict(state.crypto),
        "stock": asdict(state.stock),
        # Provide futures alias for backward compatibility with frontend
        "futures": asdict(state.stock),
        "equity_peak_usd": round(state.equity_peak_usd, 2),
        "equity_current_usd": round(state.equity_current_usd, 2),
        "engine_paused": state.engine_paused,
        "pause_reason": state.pause_reason,
    }
    # Add summary fields for backward compatibility with previous UI format
    data["crypto"]["completed"] = state.crypto.trades_this_month
    data["stock"]["completed"] = state.stock.trades_this_month
    data["futures"]["completed"] = state.stock.trades_this_month
    _atomic_write(path, data)


def _roll_periods(state: GoalState) -> None:
    """Reset daily/monthly counters when the calendar rolls over."""
    today = date.today()
    today_str = today.isoformat()
    month_str = today.strftime("%Y-%m")
    for bucket in (state.crypto, state.stock):
        if bucket.last_reset_day != today_str:
            bucket.realized_pnl_today_usd = 0.0
            bucket.last_reset_day = today_str
        if bucket.last_reset_month != month_str:
            bucket.trades_this_month = 0
            bucket.realized_pnl_this_month_usd = 0.0
            bucket.last_reset_month = month_str


# ---------------------------------------------------------------------------
# Leverage selection — derived, never a flat default
# ---------------------------------------------------------------------------

def select_leverage(
    asset_class: AssetClass,
    effective_conviction: float,   # from compute_dead_day_and_conviction(); 0 on dead days
    range_atr_ratio: float,        # from the same dict
) -> float:
    """
    Leverage scales up with conviction and down when today's range is
    already stretched relative to its own ATR (i.e. don't lever into a
    session that has already made its move).
    """
    ac: AssetClass = "crypto" if asset_class.lower() == "crypto" else "stock"
    cfg = CONFIG[ac]

    conviction_component = max(0.0, min(1.0, effective_conviction)) ** LEVERAGE_CONVICTION_EXPONENT

    # Penalize leverage as today's range approaches/exceeds its ATR norm.
    # ratio ~1.0 (normal day) -> no penalty. ratio > 1.5 (already extended) -> meaningful cut.
    stretch_penalty = 1.0 / max(1.0, range_atr_ratio / 1.2)

    raw_leverage = MIN_LEVERAGE + (cfg.max_leverage - MIN_LEVERAGE) * conviction_component * stretch_penalty
    return round(min(cfg.max_leverage, max(MIN_LEVERAGE, raw_leverage)), 2)


# ---------------------------------------------------------------------------
# Position sizing (risk-based, equity-scaled)
# ---------------------------------------------------------------------------

def position_risk_budget_usd(
    asset_class: AssetClass,
    state: Optional[GoalState] = None,
) -> float:
    """Dollar amount risked per trade. Bounded between $1.00 min floor and 5% max ceiling of live equity."""
    ac: AssetClass = "crypto" if asset_class.lower() == "crypto" else "stock"
    cfg = CONFIG[ac]
    
    use_equity_scaling = getattr(config, "ENABLE_EQUITY_RISK_SCALING", True)
    if use_equity_scaling:
        state = state or load_state()
        capital_base = max(1.0, state.equity_current_usd)
    else:
        capital_base = TOTAL_CAPITAL_USD

    allocated_capital = capital_base * (cfg.capital_allocation_pct / 100.0)
    raw_budget = allocated_capital * (cfg.risk_per_trade_pct / 100.0)
    
    # Bounded between $1.00 min floor and 5% max ceiling of current equity base
    clamped_budget = max(1.0, min(raw_budget, capital_base * 0.05))
    return round(clamped_budget, 2)



# ---------------------------------------------------------------------------
# Core gate — call this before every candidate entry
# ---------------------------------------------------------------------------

@dataclass
class TradeDecision:
    allowed: bool
    reason: str
    leverage: float = 0.0
    risk_budget_usd: float = 0.0


def evaluate_trade(
    asset_class: str,
    dead_day_result: dict,   # the dict returned by compute_dead_day_and_conviction()
    state: Optional[GoalState] = None,
    persist: bool = True,
) -> TradeDecision:
    ac: AssetClass = "crypto" if asset_class.lower() == "crypto" else "stock"
    state = state or load_state()
    _roll_periods(state)
    bucket = state.bucket(ac)
    cfg = CONFIG[ac]

    # 1. Engine-wide pause (monthly drawdown breach)
    if state.engine_paused:
        return TradeDecision(False, f"Engine paused: {state.pause_reason}")

    # 2. Monthly drawdown check (recompute in case equity moved since last save)
    drawdown_pct = (state.equity_peak_usd - state.equity_current_usd) / max(1.0, state.equity_peak_usd) * 100.0
    if drawdown_pct >= MONTHLY_DRAWDOWN_PAUSE_PCT:
        state.engine_paused = True
        state.pause_reason = f"Monthly drawdown {drawdown_pct:.1f}% >= {MONTHLY_DRAWDOWN_PAUSE_PCT}% limit"
        if persist:
            save_state(state)
        return TradeDecision(False, state.pause_reason)

    # 3. Daily loss circuit breaker (per asset-class bucket)
    daily_loss_pct = abs(min(0.0, bucket.realized_pnl_today_usd)) / TOTAL_CAPITAL_USD * 100.0
    if daily_loss_pct >= cfg.daily_loss_circuit_breaker_pct:
        return TradeDecision(
            False,
            f"{ac} daily loss circuit breaker hit "
            f"({daily_loss_pct:.1f}% >= {cfg.daily_loss_circuit_breaker_pct}%) — no new entries today"
        )

    # 4. Monthly trade ceiling (never a floor — under-trading is fine)
    if bucket.trades_this_month >= cfg.monthly_trade_ceiling:
        return TradeDecision(
            False,
            f"{ac} monthly trade ceiling reached "
            f"({bucket.trades_this_month}/{cfg.monthly_trade_ceiling})"
        )

    # 5. Dead-day gate — reuse detector's output directly
    if dead_day_result.get("is_dead_day"):
        return TradeDecision(
            False,
            f"Dead day: {dead_day_result.get('dead_day_reason', 'flagged by dead-day filter')}"
        )

    # 6. All clear -> derive leverage and risk budget, do not default
    effective_conviction = dead_day_result.get("effective_conviction", 0.0)
    range_atr_ratio = dead_day_result.get("range_atr_ratio", 1.0)

    if effective_conviction <= 0.0:
        return TradeDecision(False, "Zero effective conviction — no qualifying signal")

    leverage = select_leverage(ac, effective_conviction, range_atr_ratio)
    risk_budget = position_risk_budget_usd(ac, state)

    return TradeDecision(
        allowed=True,
        reason=f"OK — conviction={effective_conviction:.2f}, range/ATR={range_atr_ratio:.2f}",
        leverage=leverage,
        risk_budget_usd=risk_budget,
    )



def record_trade_result(
    asset_class: str,
    pnl_usd: float,
    state: Optional[GoalState] = None,
    persist: bool = True,
) -> GoalState:
    """Call after a trade closes to update counters, equity, and drawdown tracking."""
    ac: AssetClass = "crypto" if asset_class.lower() == "crypto" else "stock"
    state = state or load_state()
    _roll_periods(state)
    bucket = state.bucket(ac)

    bucket.trades_this_month += 1
    if pnl_usd > 0:
        bucket.wins += 1
        bucket.win_pnl += pnl_usd
    elif pnl_usd < 0:
        bucket.losses += 1
        bucket.loss_pnl += abs(pnl_usd)

    bucket.realized_pnl_today_usd += pnl_usd
    bucket.realized_pnl_this_month_usd += pnl_usd

    state.equity_current_usd += pnl_usd
    state.equity_peak_usd = max(state.equity_peak_usd, state.equity_current_usd)

    log.info(
        f"[GoalModule] {ac.upper()} Trade Closed (P/L: ${pnl_usd:+.2f}). "
        f"Month Trades: {bucket.trades_this_month}/{CONFIG[ac].monthly_trade_ceiling}, "
        f"Month P/L: ${bucket.realized_pnl_this_month_usd:+.2f}"
    )

    if persist:
        save_state(state)
    return state


def monthly_progress_summary(state: Optional[GoalState] = None) -> dict:
    """Informational only — never used to gate trades or force activity."""
    state = state or load_state()
    total_pnl = state.crypto.realized_pnl_this_month_usd + state.stock.realized_pnl_this_month_usd
    total_trades = state.crypto.trades_this_month + state.stock.trades_this_month
    total_wins = state.crypto.wins + state.stock.wins
    win_rate = (total_wins / total_trades * 100.0) if total_trades > 0 else 0.0

    return {
        "monthly_target_usd": round(TOTAL_CAPITAL_USD * MONTHLY_TARGET_PCT / 100.0, 2),
        "monthly_pnl_usd": round(total_pnl, 2),
        "monthly_pnl_pct": round(total_pnl / TOTAL_CAPITAL_USD * 100.0, 2),
        "crypto_trades_used": f"{state.crypto.trades_this_month}/{CONFIG['crypto'].monthly_trade_ceiling}",
        "stock_trades_used": f"{state.stock.trades_this_month}/{CONFIG['stock'].monthly_trade_ceiling}",
        "crypto_completed": state.crypto.trades_this_month,
        "crypto_ceiling": CONFIG["crypto"].monthly_trade_ceiling,
        "stock_completed": state.stock.trades_this_month,
        "stock_ceiling": CONFIG["stock"].monthly_trade_ceiling,
        "crypto_today_pnl_usd": round(state.crypto.realized_pnl_today_usd, 2),
        "stock_today_pnl_usd": round(state.stock.realized_pnl_today_usd, 2),
        "equity_current_usd": round(state.equity_current_usd, 2),
        "equity_peak_usd": round(state.equity_peak_usd, 2),
        "current_drawdown_pct": round(
            max(0.0, (state.equity_peak_usd - state.equity_current_usd) / max(1.0, state.equity_peak_usd) * 100.0), 2
        ),
        "win_rate_pct": round(win_rate, 1),
        "engine_paused": state.engine_paused,
        "pause_reason": state.pause_reason,
    }
