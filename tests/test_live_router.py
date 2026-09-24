"""
tests/test_live_router.py — Tests for the CCXT live/paper execution router
"""

import pytest
from execution.live_ccxt_router import LiveCCXTRouter


def test_ccxt_router_dry_run_execution():
    router = LiveCCXTRouter(exchange_id="binance", dry_run=True)
    
    proposed_order = {
        "order_id": "ord_test_99",
        "instrument": "BTC-USD",
        "action": "BUY",
        "dynamic_leverage": 2.5,
        "risk_budget_usd": 20.0
    }

    fill = router.execute_order(proposed_order, current_price=50000.0)

    assert fill["status"] == "filled"
    assert fill["symbol"] == "BTC-USD"
    assert fill["side"] == "buy"
    assert fill["size"] > 0
    assert fill["fill_price"] == 50000.0
    assert "CCXT_DRYRUN" in fill["venue"]
