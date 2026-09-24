"""
tests/test_chaos_execution.py — Institutional Chaos & Microstructure Resilience Tests

Validates system behavior under severe market anomalies:
1. Mid-Order Connection Drops & EMERGENCY_HALT.
2. Partial-Fill Sizing: Stops strictly match filled quantity.
3. HTTP 429 Rate-Limit Spikes & Exponential Backoff Retries.
4. Position Reconciliation Mismatches & Exchange Ground Truth Sync.
5. Feed Lag & Quiet-System Heartbeat Alerts.
6. Realistic Cost Friction (Slippage, Spread, Fees, Latency).
7. Meta-Labeling Secondary ML Signal Veto & Sizing.
"""

import time
import pytest
from unittest.mock import MagicMock

from core.order_intent import OrderIntent, OrderLeg, OrderSide, OrderType, IntentType
from execution.hardened_ccxt_router import HardenedCCXTRouter, RouterState, OrderStatus
from execution.fill_model import RealisticFillModel, realistic_fill_model
from middleware.system_monitor import SystemMonitor, AlertSeverity
from brain.meta_labeling import MetaLabelClassifier, TripleBarrierLabeler
import pandas as pd
import numpy as np


def test_mid_order_connection_drop_chaos():
    monitor = SystemMonitor()
    router = HardenedCCXTRouter(dry_run=True)
    
    # 1. Connection drops
    router.handle_connection_drop("Exchange WebSocket abruptly closed (ECONNRESET)")
    assert router.state == RouterState.EMERGENCY_HALT

    # 2. Subsequent trade intent must be immediately rejected
    intent = OrderIntent(
        strategy_id="strat_chaos",
        sleeve_id="sleeve_01",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)]
    )

    results = router.execute_intent(intent, current_prices={"BTC-USD": 50000.0})
    assert len(results) == 1
    assert results[0]["status"] == OrderStatus.REJECTED.value
    assert results[0]["error"] == "EMERGENCY_HALT"


def test_partial_fill_sizing_and_native_stops():
    router = HardenedCCXTRouter(dry_run=False)
    
    # Mock exchange client returning a partial fill
    mock_client = MagicMock()
    # 0.012 BTC filled out of 0.020 BTC requested
    mock_client.create_order.side_effect = [
        {"id": "ord_primary_123", "filled": 0.012, "remaining": 0.008, "price": 50000.0},  # Primary order
        {"id": "ord_stop_456"}                                                              # Stop order
    ]
    router._exchange_client = mock_client

    intent = OrderIntent(
        strategy_id="strat_partial",
        sleeve_id="sleeve_01",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)], # target 0.02 BTC @ 50k
        stop_loss_price=48000.0
    )

    results = router.execute_intent(intent, current_prices={"BTC-USD": 50000.0})
    assert len(results) == 1
    res = results[0]

    assert res["status"] == OrderStatus.PARTIALLY_FILLED.value
    assert res["filled_qty"] == 0.012
    assert res["remaining_qty"] == 0.008
    assert res["native_stop_id"] == "ord_stop_456"

    # CRITICAL: Verify stop order was sized strictly to 0.012 (actual fill), NOT 0.020!
    assert mock_client.create_order.call_count == 2
    stop_call_kwargs = mock_client.create_order.call_args_list[1][1]
    assert stop_call_kwargs["amount"] == 0.012
    assert stop_call_kwargs["params"]["stopPrice"] == 48000.0


def test_rate_limit_429_exponential_backoff_retry():
    router = HardenedCCXTRouter(dry_run=False, max_retries=3)
    
    # Mock function failing twice with 429 then succeeding on 3rd attempt
    mock_exchange_call = MagicMock()
    mock_exchange_call.side_effect = [
        Exception("HTTP 429 Too Many Requests: Rate limit exceeded"),
        Exception("Rate limit 429 IP banned temporarily"),
        {"status": "ok", "order_id": "success_123"}
    ]

    # Should succeed after 2 retries
    res = router._execute_with_retry(mock_exchange_call)
    assert res["status"] == "ok"
    assert mock_exchange_call.call_count == 3


def test_position_reconciliation_mismatch_detection():
    monitor = SystemMonitor()
    router = HardenedCCXTRouter(dry_run=False)
    
    # Local state has no BTC position
    router._local_positions = {"BTC-USD": 0.0}

    # Exchange reports open position of 0.05 BTC (e.g. manual trade outside bot)
    mock_client = MagicMock()
    mock_client.fetch_positions.return_value = [{"symbol": "BTC-USD", "contracts": 0.05}]
    mock_client.fetch_open_orders.return_value = []
    router._exchange_client = mock_client

    reconciled = router.reconcile_positions()
    
    # Discrepancy must be flagged
    assert reconciled["synced"] is False
    assert len(reconciled["discrepancies"]) == 1
    assert "Position mismatch on BTC-USD" in reconciled["discrepancies"][0]

    # Local state must be synchronized to exchange ground truth
    assert router._local_positions["BTC-USD"] == 0.05


def test_feed_lag_and_heartbeat_watchdog():
    monitor = SystemMonitor(max_feed_lag_sec=1.5, heartbeat_timeout_sec=0.1)

    # 1. Normal fresh tick -> no alert
    now = time.time()
    alert1 = monitor.record_feed_tick("BTC-USD", now - 0.05)
    assert alert1 is None

    # 2. Stale tick (lag = 3.0s > 1.5s) -> Warning alert
    alert2 = monitor.record_feed_tick("BTC-USD", now - 3.0)
    assert alert2 is not None
    assert alert2.alert_type == "FEED_LAG_DETECTED"
    assert alert2.severity == AlertSeverity.WARNING

    # 3. System quiet heartbeat timeout (> 0.1s sleep)
    time.sleep(0.15)
    heartbeat_alert = monitor.check_heartbeat()
    assert heartbeat_alert is not None
    assert heartbeat_alert.alert_type == "SYSTEM_QUIET_HEARTBEAT"
    assert heartbeat_alert.severity == AlertSeverity.CRITICAL


def test_realistic_fill_and_cost_friction():
    model = RealisticFillModel(
        crypto_taker_fee_pct=0.0004,
        base_spread_pct=0.0002,
        slippage_coeff=0.05
    )

    # Market Buy Order of $5,000 BTC @ $50,000 mid-price
    fill = model.simulate_fill(
        symbol="BTC-USD",
        side=OrderSide.BUY,
        order_type=OrderType.MARKET,
        mid_price=50000.0,
        target_size_usd=5000.0,
        adv_usd=10_000_000.0
    )

    # Price must be worse than mid due to spread and slippage
    assert fill.filled_price > fill.mid_price
    assert fill.fee_usd > 0.0
    assert fill.slippage_usd > 0.0
    assert fill.spread_cost_usd > 0.0
    assert fill.simulated_latency_ms >= 5.0
    assert fill.total_transaction_cost_usd > 0.0


def test_meta_labeling_veto_and_sizing():
    meta = MetaLabelClassifier(min_probability_threshold=0.55)
    
    # Synthetic training data
    np.random.seed(42)
    n = 100
    df_features = pd.DataFrame({
        "volatility": np.random.uniform(0.005, 0.03, n),
        "order_book_imbalance": np.random.uniform(-0.8, 0.8, n),
        "rsi_divergence": np.random.uniform(-1, 1, n),
        "volume_zscore": np.random.uniform(-2, 3, n),
        "conviction": np.random.uniform(0.5, 1.0, n)
    })
    # Target: High OBI + High Conviction tends to win
    y = ((df_features["order_book_imbalance"] > 0) & (df_features["conviction"] > 0.7)).astype(int)

    meta.train(df_features, y)
    assert meta.is_trained is True

    intent = OrderIntent(
        strategy_id="strat_ml",
        sleeve_id="sleeve_01",
        intent_type=IntentType.ENTRY,
        legs=[OrderLeg(symbol="BTC-USD", side=OrderSide.BUY, target_size_usd=1000.0)]
    )

    # Good features -> Approved with sized up multiplier
    f_good = {"volatility": 0.01, "order_book_imbalance": 0.7, "rsi_divergence": 0.5, "volume_zscore": 2.0, "conviction": 0.9}
    should_exec, prob, size_mult = meta.evaluate_trade_intent(intent, f_good)
    assert should_exec is True
    assert prob >= 0.55
    assert size_mult >= 1.0

    # Bad features -> Vetoed
    f_bad = {"volatility": 0.03, "order_book_imbalance": -0.8, "rsi_divergence": -0.5, "volume_zscore": -1.5, "conviction": 0.4}
    should_exec_bad, prob_bad, size_mult_bad = meta.evaluate_trade_intent(intent, f_bad)
    assert should_exec_bad is False
    assert prob_bad < 0.55
    assert size_mult_bad == 0.0
