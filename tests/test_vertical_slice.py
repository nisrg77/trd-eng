"""
tests/test_vertical_slice.py — End-to-End Vertical Slice Integration Test

Demonstrates and verifies the complete institutional order lifecycle:
Synthetic Ticks -> Feature Standardizer -> BollingerReversionStrategy ->
StrategyValidator (30ms watchdog) -> HardenedRiskGuard (Drawdown/Exposure) ->
HardenedCCXTRouter (Idempotency & Native Stops) -> Fill & Position Tracking -> Exit.
"""

import time
import numpy as np
import pandas as pd
import pytest

from core.order_intent import OrderIntent, OrderLeg, OrderSide, IntentType, PositionContext
from data_pipeline.feature_standardizer import compute_standard_features
from strategies.crypto.bollinger_reversion import BollingerReversionStrategy
from strategies.strategy_validator import StrategyValidator
from goals.hardened_risk_guard import HardenedRiskGuard
from goals.goal_module import GoalState
from execution.hardened_ccxt_router import HardenedCCXTRouter, RouterState, OrderStatus


def generate_synthetic_market_data(n_bars: int = 50, start_price: float = 100.0) -> pd.DataFrame:
    """Generates synthetic OHLCV data ending with a controlled price dip."""
    np.random.seed(42)
    timestamps = pd.date_range("2026-09-01", periods=n_bars, freq="1h")
    
    # Generate random walk for first n-5 bars
    returns = np.random.normal(0, 0.005, n_bars)
    prices = [start_price]
    for r in returns[1:]:
        prices.append(prices[-1] * (1 + r))
    
    # Artificially drop the last 3 bars to trigger lower Bollinger band breach & RSI dip
    prices[-3] = prices[-4] * 0.96
    prices[-2] = prices[-3] * 0.95
    prices[-1] = prices[-2] * 0.94

    df = pd.DataFrame({
        "timestamp": timestamps,
        "open": prices,
        "high": [p * 1.002 for p in prices],
        "low": [p * 0.998 for p in prices],
        "close": prices,
        "volume": [1000.0] * n_bars
    })
    return df


def test_vertical_slice_full_lifecycle():
    # 1. Initialize components
    strategy = BollingerReversionStrategy(
        strategy_id="strat_boll_slice",
        sleeve_id="sleeve_crypto_mean_rev",
        params={"allocation_usd": 1000.0, "rsi_buy_threshold": 40.0}
    )
    validator = StrategyValidator(timeout_sec=0.05)
    risk_guard = HardenedRiskGuard(
        max_monthly_loss_usd=-1000.0,
        max_position_size_usd=5000.0,
        max_gross_exposure_usd=20000.0
    )
    router = HardenedCCXTRouter(dry_run=True)
    symbol = "BTC-USD"
    fresh_goal_state = GoalState()

    # 2. Feed market data with price dip -> trigger ENTRY
    df_dip = generate_synthetic_market_data(50, start_price=100.0)
    current_px = float(df_dip.iloc[-1]["close"])
    
    # Evaluate with watchdog
    intent = validator.execute_with_watchdog(
        strategy.evaluate,
        symbol=symbol,
        df=df_dip,
        position_context=None
    )
    assert intent is not None
    assert intent.intent_type == IntentType.ENTRY
    assert intent.legs[0].side == OrderSide.BUY
    assert intent.stop_loss_price is not None
    assert intent.stop_loss_price < current_px

    # Risk Guard Evaluation
    approved, reason, approved_size = risk_guard.evaluate_intent(
        intent,
        open_positions={},
        unrealized_pnl_usd=0.0,
        goal_state=fresh_goal_state
    )
    assert approved is True
    assert approved_size == 1000.0

    # Router Execution
    exec_results = router.execute_intent(intent, current_prices={symbol: current_px})
    assert len(exec_results) == 1
    entry_fill = exec_results[0]
    assert entry_fill["status"] == OrderStatus.FILLED.value
    assert entry_fill["side"] == "BUY"
    assert entry_fill["native_stop_id"] is not None
    qty_filled = entry_fill["qty"]

    # 3. Simulate holding state (Price hasn't reached middle band yet)
    pos_context = PositionContext(
        symbol=symbol,
        qty=qty_filled,
        entry_price=current_px,
        mark_price=current_px * 1.01,
        unrealized_pnl=qty_filled * (current_px * 0.01),
        opened_at_epoch=time.time()
    )
    
    # Strategy evaluation while holding below middle band -> should return None
    hold_intent = validator.execute_with_watchdog(
        strategy.evaluate,
        symbol=symbol,
        df=df_dip,
        position_context=pos_context
    )
    assert hold_intent is None

    # 4. Price rallies past middle band -> triggers EXIT
    df_feat = compute_standard_features(df_dip.copy())
    bb_middle = float(df_feat.iloc[-1]["bb_middle"])
    rally_px = bb_middle + 10.0
    df_rally = df_dip.copy()
    df_rally.iloc[-1, df_rally.columns.get_loc("close")] = rally_px

    exit_intent = validator.execute_with_watchdog(
        strategy.evaluate,
        symbol=symbol,
        df=df_rally,
        position_context=pos_context
    )
    assert exit_intent is not None
    assert exit_intent.intent_type == IntentType.EXIT
    assert exit_intent.legs[0].side == OrderSide.SELL

    # Risk Guard approves EXIT
    exit_approved, _, _ = risk_guard.evaluate_intent(
        exit_intent,
        open_positions={symbol: {"qty": qty_filled, "entry_price": current_px}},
        unrealized_pnl_usd=100.0,
        goal_state=fresh_goal_state
    )
    assert exit_approved is True

    # Router fills EXIT
    exit_results = router.execute_intent(exit_intent, current_prices={symbol: rally_px})
    assert len(exit_results) == 1
    assert exit_results[0]["status"] == OrderStatus.FILLED.value
    assert exit_results[0]["side"] == "SELL"


def test_vertical_slice_risk_guard_blocks_oversized_intent():
    strategy = BollingerReversionStrategy(
        strategy_id="strat_boll_slice",
        sleeve_id="sleeve_crypto_mean_rev",
        params={"allocation_usd": 15000.0}  # Exceeds max position size of $5,000
    )
    validator = StrategyValidator(timeout_sec=0.05)
    risk_guard = HardenedRiskGuard(max_position_size_usd=5000.0)
    router = HardenedCCXTRouter(dry_run=True)
    symbol = "BTC-USD"
    fresh_goal_state = GoalState()

    df_dip = generate_synthetic_market_data(50, start_price=100.0)
    intent = validator.execute_with_watchdog(
        strategy.evaluate,
        symbol=symbol,
        df=df_dip,
        position_context=None
    )
    assert intent is not None

    # Risk guard blocks
    approved, reason, _ = risk_guard.evaluate_intent(
        intent,
        open_positions={},
        goal_state=fresh_goal_state
    )
    assert approved is False
    assert "exceeds max position size" in reason


def test_vertical_slice_disconnect_safeguard():
    router = HardenedCCXTRouter(dry_run=True)
    router.handle_connection_drop("Exchange WebSocket Heartbeat Missing")
    assert router.state == RouterState.EMERGENCY_HALT

    intent = OrderIntent(
        strategy_id="strat_test",
        sleeve_id="sleeve_test",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)]
    )

    results = router.execute_intent(intent, current_prices={"BTC-USD": 100.0})
    assert results[0]["status"] == OrderStatus.REJECTED.value
    assert results[0]["error"] == "EMERGENCY_HALT"
