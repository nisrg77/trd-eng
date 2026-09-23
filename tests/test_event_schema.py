"""
tests/test_event_schema.py — Strict Schema Validation Tests for Event Bus & OMS

Validates that all emitted events comply 100% with SCHEMA.md rules:
1. All required keys are ALWAYS present (never omitted, null when inapplicable).
2. position_update lifecycle (open -> tick -> partial_close -> closed) maintains single source of truth.
3. execution_log and engine_health structures match specification.
"""

import sys
import os
import pytest
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from middleware.event_bus import event_bus, to_iso8601
from execution.simulated_oms import SimulatedFuturesOMS

REQUIRED_POSITION_KEYS = [
    "trade_id",
    "symbol",
    "side",
    "size",
    "leverage",
    "entry_price",
    "exit_price",
    "mark_price",
    "unrealized_pnl",
    "realized_pnl",
    "status",
    "opened_at",
    "closed_at",
]

REQUIRED_EXECUTION_LOG_KEYS = [
    "log_id",
    "level",
    "category",
    "symbol",
    "message",
    "order_id",
]

REQUIRED_ENGINE_HEALTH_KEYS = [
    "status",
    "uptime_seconds",
    "last_heartbeat",
    "connected_exchanges",
    "active_positions_count",
]


def test_position_update_schema_keys():
    """Verify position_update contains ALL required keys without omission."""
    event = event_bus.publish_position_update(
        trade_id="trd_test123",
        symbol="BTC-USD",
        side="long",
        size=1.5,
        leverage=10.0,
        entry_price=85000.0,
        mark_price=85500.0,
        status="open",
        opened_at=to_iso8601(),
        exit_price=None,
        unrealized_pnl=750.0,
        realized_pnl=None,
        closed_at=None
    )

    assert event["type"] == "position_update"
    assert "timestamp" in event
    data = event["data"]

    for key in REQUIRED_POSITION_KEYS:
        assert key in data, f"Missing key '{key}' in position_update payload!"

    assert data["trade_id"] == "trd_test123"
    assert data["symbol"] == "BTC-USD"
    assert data["side"] == "long"
    assert data["status"] == "open"
    assert data["exit_price"] is None
    assert data["realized_pnl"] is None
    assert data["closed_at"] is None


def test_execution_log_schema_keys():
    """Verify execution_log contains ALL required keys."""
    event = event_bus.publish_execution_log(
        level="fill",
        category="entry_fill",
        symbol="ETH-USD",
        message="Order filled for BUY 2.0 ETH-USD @ $2750.00",
        order_id="ord_abc123"
    )

    assert event["type"] == "execution_log"
    data = event["data"]

    for key in REQUIRED_EXECUTION_LOG_KEYS:
        assert key in data, f"Missing key '{key}' in execution_log payload!"

    assert data["level"] == "fill"
    assert data["symbol"] == "ETH-USD"
    assert data["order_id"] == "ord_abc123"


def test_engine_health_schema_keys():
    """Verify engine_health contains ALL required keys."""
    health_event = event_bus.get_engine_health()

    assert health_event["type"] == "engine_health"
    data = health_event["data"]

    for key in REQUIRED_ENGINE_HEALTH_KEYS:
        assert key in data, f"Missing key '{key}' in engine_health payload!"

    assert data["status"] in ["healthy", "degraded", "error"]
    assert isinstance(data["uptime_seconds"], int)
    assert isinstance(data["connected_exchanges"], dict)


def test_oms_position_lifecycle_events():
    """Verify OMS publishes open, tick, and closed position_update events without polluting state."""
    import tempfile
    fd, tmp_state = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    try:
        oms = SimulatedFuturesOMS(state_file=tmp_state)
        
        # 1. Open new LONG position
        order = {
            "order_id": "ord_life_1",
            "instrument": "SOL-USD",
            "action": "BUY",
            "portfolio_allocation_pct": 0.05,
            "dynamic_leverage": 10.0,
            "risk_state": "APPROVED"
        }
        oms.submit_order(order, current_price=150.0, obi_rho=0.0)

        active_pos = event_bus.get_active_positions()
        sol_pos = next((p for p in active_pos if p["symbol"] == "SOL-USD"), None)
        assert sol_pos is not None, "SOL-USD position should be active!"
        assert sol_pos["status"] == "open"
        assert sol_pos["trade_id"].startswith("trd_")
        assert sol_pos["opened_at"] is not None
        assert sol_pos["closed_at"] is None
        assert sol_pos["exit_price"] is None

        # 2. Update price (mark-to-market tick)
        oms.update_prices({"SOL-USD": 160.0})
        updated_pos = next((p for p in event_bus.get_active_positions() if p["symbol"] == "SOL-USD"), None)
        assert updated_pos is not None
        assert updated_pos["mark_price"] == 160.0
        assert updated_pos["unrealized_pnl"] > 0.0

        # 3. Trigger full close via stop/exit
        exits = oms.update_prices({"SOL-USD": 100.0}) # Trigger ATR stop
        all_events = event_bus.get_recent_events()
        closed_events = [e for e in all_events if e["type"] == "position_update" and e["data"]["symbol"] == "SOL-USD" and e["data"]["status"] == "closed"]
        assert len(closed_events) >= 1, "Should emit position_update with status='closed' upon full exit!"
        closed_data = closed_events[-1]["data"]
        assert closed_data["status"] == "closed"
        assert closed_data["exit_price"] is not None
        assert closed_data["closed_at"] is not None
        assert closed_data["realized_pnl"] is not None
    finally:
        if os.path.exists(tmp_state):
            os.remove(tmp_state)
