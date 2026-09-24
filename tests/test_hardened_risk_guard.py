"""
tests/test_hardened_risk_guard.py — Tests for institutional risk boundaries and emergency kill switch
"""

import pytest
from core.order_intent import OrderIntent, OrderLeg, OrderSide, IntentType
from goals.hardened_risk_guard import HardenedRiskGuard
from goals.goal_module import GoalState, BucketState


def _make_intent(intent_type=IntentType.ENTRY, size_usd=1000.0, symbol="BTC-USD"):
    return OrderIntent(
        strategy_id="strat_01",
        sleeve_id="sleeve_01",
        intent_type=intent_type,
        legs=[OrderLeg(symbol=symbol, side=OrderSide.BUY, target_size_usd=size_usd)]
    )


def test_hardened_risk_guard_approves_safe_intent():
    rg = HardenedRiskGuard(max_monthly_loss_usd=-1000.0, max_position_size_usd=5000.0)
    intent = _make_intent()
    state = GoalState()

    approved, reason, size = rg.evaluate_intent(intent, open_positions={}, unrealized_pnl_usd=0.0, goal_state=state)
    assert approved is True
    assert "passed" in reason.lower()
    assert size == 1000.0


def test_emergency_kill_switch_behavior():
    rg = HardenedRiskGuard()
    rg.trigger_emergency_kill_switch(reason="Market flash crash alert")

    assert rg.is_kill_switch_active is True

    # 1. Entry must be blocked
    entry_intent = _make_intent(intent_type=IntentType.ENTRY)
    approved, reason, _ = rg.evaluate_intent(entry_intent, open_positions={}, goal_state=GoalState())
    assert approved is False
    assert "kill switch" in reason.lower()

    # 2. Exit MUST be allowed through to de-risk
    exit_intent = _make_intent(intent_type=IntentType.EXIT)
    approved_exit, reason_exit, _ = rg.evaluate_intent(exit_intent, open_positions={}, goal_state=GoalState())
    assert approved_exit is True
    assert "exit permitted" in reason_exit.lower()

    # 3. Reset kill switch
    rg.reset_kill_switch()
    assert rg.is_kill_switch_active is False


def test_monthly_loss_floor_includes_unrealized_mtm():
    rg = HardenedRiskGuard(max_monthly_loss_usd=-1000.0)
    
    # State has -$600 realized loss
    state = GoalState(crypto=BucketState(realized_pnl_this_month_usd=-600.0))

    # Unrealized mark-to-market is -$500 -> Total PnL is -$1100 (breaches -$1000 limit!)
    intent = _make_intent()
    approved, reason, _ = rg.evaluate_intent(intent, open_positions={}, unrealized_pnl_usd=-500.0, goal_state=state)

    assert approved is False
    assert "breached monthly floor" in reason.lower()
    assert state.engine_paused is True


def test_max_position_size_limit():
    rg = HardenedRiskGuard(max_position_size_usd=3000.0)
    intent_too_big = _make_intent(size_usd=5000.0)

    approved, reason, _ = rg.evaluate_intent(intent_too_big, open_positions={}, goal_state=GoalState())
    assert approved is False
    assert "exceeds max position size" in reason.lower()
