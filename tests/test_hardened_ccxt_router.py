"""
tests/test_hardened_ccxt_router.py — Tests for HardenedCCXTRouter, native stops, and reconciliation
"""

import pytest
from core.order_intent import OrderIntent, OrderLeg, OrderSide, IntentType
from execution.hardened_ccxt_router import HardenedCCXTRouter, RouterState, OrderStatus


def test_client_order_id_generation():
    router = HardenedCCXTRouter(dry_run=True)
    id1 = router.generate_client_order_id("nfi_strat", "BTC-USD")
    id2 = router.generate_client_order_id("nfi_strat", "BTC-USD")

    assert id1.startswith("cl_nfi_st_BTCUSD_")
    assert id1 != id2  # Unique suffixes prevent collision


def test_execute_intent_with_native_stop():
    router = HardenedCCXTRouter(dry_run=True)
    intent = OrderIntent(
        strategy_id="strat_01",
        sleeve_id="sleeve_01",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)],
        stop_loss_price=48500.0
    )

    results = router.execute_intent(intent, current_prices={"BTC-USD": 50000.0})
    assert len(results) == 1
    res = results[0]

    assert res["status"] == OrderStatus.FILLED.value
    assert res["symbol"] == "BTC-USD"
    assert res["side"] == "BUY"
    assert res["qty"] == 0.02
    assert res["native_stop_id"] is not None  # Server-side native stop registered


def test_connection_drop_triggers_emergency_halt():
    router = HardenedCCXTRouter(dry_run=True)
    
    # 1. Simulate connection drop
    router.handle_connection_drop(reason="Exchange WS ping timeout")
    assert router.state == RouterState.EMERGENCY_HALT

    # 2. Subsequent orders must be rejected immediately (zero silent fallback!)
    intent = OrderIntent(
        strategy_id="strat_01",
        sleeve_id="sleeve_01",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)]
    )

    results = router.execute_intent(intent, current_prices={"BTC-USD": 50000.0})
    assert len(results) == 1
    assert results[0]["status"] == OrderStatus.REJECTED.value
    assert results[0]["error"] == "EMERGENCY_HALT"


def test_reconciliation():
    router = HardenedCCXTRouter(dry_run=True)
    reconciled = router.reconcile_positions()
    assert reconciled["synced"] is True
    assert isinstance(reconciled["positions"], dict)
    assert router.state == RouterState.READY
