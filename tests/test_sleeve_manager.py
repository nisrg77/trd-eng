"""
tests/test_sleeve_manager.py — Unit Tests for Capital Sleeves & Regime Routing
"""

import pytest
from core.order_intent import OrderIntent, OrderLeg, OrderSide, IntentType
from strategies.sleeve_manager import SleeveManager, CapitalSleeve


def test_independent_sleeves_opposing_signals_no_cancel():
    mgr = SleeveManager()
    
    # 1. Register two independent sleeves
    trend_sleeve = CapitalSleeve(sleeve_id="sleeve_trend", allocated_capital_usd=5000.0)
    mean_rev_sleeve = CapitalSleeve(sleeve_id="sleeve_mean_rev", allocated_capital_usd=5000.0)
    
    mgr.register_sleeve(trend_sleeve)
    mgr.register_sleeve(mean_rev_sleeve)

    # 2. Strategy A (ORB Breakout) emits BUY $1,000 BTC
    intent_buy = OrderIntent(
        strategy_id="strat_orb",
        sleeve_id="sleeve_trend",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)]
    )

    # 3. Strategy B (VPOC Reversion) emits SELL $1,000 BTC
    intent_sell = OrderIntent(
        strategy_id="strat_vpoc",
        sleeve_id="sleeve_mean_rev",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.SELL, target_size_usd=1000.0)]
    )

    # 4. Both intents pass independently (NO CANCELLATION TO ZERO!)
    appr_buy, reason_buy = mgr.route_intent(intent_buy)
    appr_sell, reason_sell = mgr.route_intent(intent_sell)

    assert appr_buy is True
    assert appr_sell is True

    # 5. Record fills into isolated sleeve accounts
    mgr.record_fill("sleeve_trend", "BTC-USD", OrderSide.BUY, qty=0.02, price=50000.0, intent_type=IntentType.ENTRY)
    mgr.record_fill("sleeve_mean_rev", "BTC-USD", OrderSide.SELL, qty=0.02, price=50000.0, intent_type=IntentType.ENTRY)

    # 6. Verify positions are isolated
    ctx_trend = mgr.get_position_context("sleeve_trend", "BTC-USD", current_mark_price=51000.0)
    ctx_mean = mgr.get_position_context("sleeve_mean_rev", "BTC-USD", current_mark_price=51000.0)

    assert ctx_trend.qty == 0.02
    assert ctx_trend.unrealized_pnl > 0.0   # Long in profit
    assert ctx_mean.qty == -0.02
    assert ctx_mean.unrealized_pnl < 0.0    # Short in loss


def test_regime_filtering():
    mgr = SleeveManager()
    mgr.register_sleeve(CapitalSleeve(sleeve_id="sleeve_trend", allocated_capital_usd=5000.0, regime_mode="TRENDING"))
    mgr.register_sleeve(CapitalSleeve(sleeve_id="sleeve_range", allocated_capital_usd=5000.0, regime_mode="RANGING"))

    mgr.set_symbol_regime("BTC-USD", "TRENDING")

    intent_trend = OrderIntent(
        strategy_id="strat_orb",
        sleeve_id="sleeve_trend",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)]
    )
    intent_range = OrderIntent(
        strategy_id="strat_vpoc",
        sleeve_id="sleeve_range",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.SELL, target_size_usd=1000.0)]
    )

    # Trend sleeve allowed, Range sleeve blocked by regime filter
    assert mgr.route_intent(intent_trend)[0] is True
    assert mgr.route_intent(intent_range)[0] is False


def test_sleeve_capital_exhaustion():
    mgr = SleeveManager()
    mgr.register_sleeve(CapitalSleeve(sleeve_id="sleeve_micro", allocated_capital_usd=1500.0))

    intent = OrderIntent(
        strategy_id="strat_test",
        sleeve_id="sleeve_micro",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="ETH-USD", side=OrderSide.BUY, target_size_usd=2000.0)]
    )

    approved, reason = mgr.route_intent(intent)
    assert approved is False
    assert "Insufficient sleeve capital" in reason


def test_multi_leg_arbitrage_intent():
    mgr = SleeveManager()
    mgr.register_sleeve(CapitalSleeve(sleeve_id="sleeve_arb", allocated_capital_usd=10000.0, regime_mode="ALL"))

    # Multi-leg Funding Rate Arbitrage (Long Spot + Short Perp)
    arb_intent = OrderIntent(
        strategy_id="strat_funding_arb",
        sleeve_id="sleeve_arb",
        intent_type=IntentType.ENTRY,
        legs=[
            OrderLeg(symbol="BTC-SPOT", side=OrderSide.BUY, target_size_usd=2000.0, venue="BINANCE_SPOT"),
            OrderLeg(symbol="BTC-PERP", side=OrderSide.SELL, target_size_usd=2000.0, venue="BINANCE_PERP")
        ]
    )

    assert arb_intent.is_multi_leg is True
    approved, reason = mgr.route_intent(arb_intent)
    assert approved is True
