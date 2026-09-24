"""
tests/test_order_intent.py — Tests for OrderIntent, PositionContext, and Watchdog Validator
"""

import time
import pytest
import pandas as pd
from core.order_intent import OrderIntent, OrderLeg, OrderSide, OrderType, IntentType, PositionContext
from strategies.strategy_validator import StrategyValidator


def test_order_intent_single_leg_validation():
    leg = OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)
    intent = OrderIntent(
        strategy_id="strat_01",
        sleeve_id="sleeve_alpha",
        intent_type=IntentType.ENTRY,
        legs=[leg],
        stop_loss_price=48000.0,
        take_profit_price=54000.0,
        conviction=0.85
    )

    is_valid, reason = intent.validate()
    assert is_valid is True
    assert intent.is_multi_leg is False
    assert intent.is_expired is False


def test_order_intent_multi_leg_funding_arb():
    # Long Spot + Short Perp
    leg_spot = OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=2500.0, venue="BINANCE_SPOT")
    leg_perp = OrderLeg(symbol="BTC-USD", side=OrderSide.SELL, target_size_usd=2500.0, venue="BINANCE_PERP")

    intent = OrderIntent(
        strategy_id="funding_arb_01",
        sleeve_id="delta_neutral",
        intent_type=IntentType.ENTRY,
        legs=[leg_spot, leg_perp],
        conviction=0.95
    )

    is_valid, _ = intent.validate()
    assert is_valid is True
    assert intent.is_multi_leg is True
    assert len(intent.legs) == 2


def test_order_intent_rejects_nans_and_invalid_prices():
    # Leg with negative size
    bad_leg = OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=-500.0)
    intent = OrderIntent(
        strategy_id="bad_strat",
        sleeve_id="sleeve_test",
        intent_type=IntentType.ENTRY,
        legs=[bad_leg]
    )
    is_valid, reason = intent.validate()
    assert is_valid is False
    assert "invalid" in reason.lower()

    # Intent with NaN stop loss
    leg_ok = OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=500.0)
    intent_nan = OrderIntent(
        strategy_id="bad_strat",
        sleeve_id="sleeve_test",
        intent_type=IntentType.ENTRY,
        legs=[leg_ok],
        stop_loss_price=float("nan")
    )
    is_valid_nan, reason_nan = intent_nan.validate()
    assert is_valid_nan is False
    assert "stop_loss_price" in reason_nan


def test_position_context():
    pos = PositionContext(
        symbol="ETH-USD",
        qty=2.5,
        entry_price=3000.0,
        mark_price=3150.0,
        unrealized_pnl=375.0,
        opened_at_epoch=time.time() - 120.0
    )
    assert pos.is_open is True
    assert pos.side == OrderSide.BUY
    assert pos.holding_duration_sec >= 100.0


def test_watchdog_timeout_aborts_hanging_strategy():
    validator = StrategyValidator(timeout_sec=0.030)  # 30ms

    def fast_strategy(sym, df, pos):
        return OrderIntent(
            strategy_id="fast_strat",
            sleeve_id="sleeve_fast",
            intent_type=IntentType.ENTRY,
            legs=[OrderLeg(symbol=sym, side=OrderSide.BUY, target_size_usd=500.0)]
        )

    def hanging_strategy(sym, df, pos):
        time.sleep(0.100)  # 100ms sleep exceeds 30ms limit
        return OrderIntent(
            strategy_id="hung_strat",
            sleeve_id="sleeve_hung",
            intent_type=IntentType.ENTRY,
            legs=[OrderLeg(symbol=sym, side=OrderSide.BUY, target_size_usd=500.0)]
        )

    df_dummy = pd.DataFrame({"close": [100.0]})

    # Fast strategy succeeds
    res_fast = validator.execute_with_watchdog(fast_strategy, "BTC-USD", df_dummy)
    assert res_fast is not None
    assert res_fast.strategy_id == "fast_strat"

    # Hanging strategy is aborted cleanly by the watchdog without throwing an unhandled exception
    res_hung = validator.execute_with_watchdog(hanging_strategy, "BTC-USD", df_dummy)
    assert res_hung is None
