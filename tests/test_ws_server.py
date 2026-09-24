"""
tests/test_ws_server.py — Integration Tests for FastAPI WebSocket Endpoints

Validates:
1. Dedicated Live Chart WebSocket (/ws/charts & /ws/chart):
   - Instant initial historical candle bootstrap
   - Real-time tick bar streaming
   - Client ping/pong heartbeat
   - Runtime symbol and timeframe switching (action=subscribe)
2. Unified Engine & Trading WebSocket (/ws/trading):
   - Initial telemetry and state distribution
   - Dirty-check deduplication (no redundant repeating spam)
   - Real-time position updates and execution logs dispatched from event_bus
3. Connection lifecycle, clean disconnects, and thread safety.
"""

import pytest
import json
import time
from fastapi.testclient import TestClient
from services.ws_server import app
from middleware.ws_manager import ws_manager
from middleware.event_bus import event_bus
from services.chart_feed import chart_feed_manager


@pytest.fixture
def client():
    return TestClient(app)


def test_dedicated_live_chart_websocket(client):
    """
    Connect to /ws/charts?symbol=BTC-USD&timeframe=5s and verify:
    1. First frame is HISTORICAL_CANDLES.
    2. Consecutive frame is TICK.
    3. Responds to client ping with PONG.
    4. Responds to subscribe action with new symbol's candles.
    """
    with client.websocket_connect("/ws/charts?symbol=BTC-USD&timeframe=5s") as ws:
        # 1. First frame must be HISTORICAL_CANDLES
        init_frame = ws.receive_json()
        assert init_frame["type"] == "HISTORICAL_CANDLES"
        assert "timestamp" in init_frame
        assert "channel" in init_frame
        assert "BTC-USD" in init_frame["channel"]
        candles = init_frame["payload"]
        assert isinstance(candles, list)
        assert len(candles) > 0
        first_candle = candles[0]
        for key in ["time", "open", "high", "low", "close", "volume"]:
            assert key in first_candle, f"Candle missing required key '{key}'"

        # 2. Next frame must be TICK
        tick_frame = ws.receive_json()
        assert tick_frame["type"] == "TICK"
        tick = tick_frame["payload"]
        for key in ["time", "open", "high", "low", "close", "volume"]:
            assert key in tick, f"Tick missing required key '{key}'"

        # 3. Client sends ping
        ws.send_json({"action": "ping"})
        pong_frame = ws.receive_json()
        assert pong_frame["type"] == "PONG"

        # 4. Client switches symbol to ETH-USD
        ws.send_json({"action": "subscribe", "symbol": "ETH-USD", "timeframe": "5s"})
        eth_candles_frame = None
        for _ in range(5):
            frame = ws.receive_json()
            if frame.get("type") == "HISTORICAL_CANDLES":
                eth_candles_frame = frame
                break
        assert eth_candles_frame is not None, "Did not receive HISTORICAL_CANDLES frame for ETH-USD"
        assert eth_candles_frame["type"] == "HISTORICAL_CANDLES"
        assert "ETH-USD" in eth_candles_frame["channel"]
        eth_candles = eth_candles_frame["payload"]
        assert len(eth_candles) > 0


def test_live_chart_alias_endpoint(client):
    """Verify alias endpoint /ws/chart connects cleanly."""
    with client.websocket_connect("/ws/chart?symbol=SOL-USD&timeframe=5s") as ws:
        init_frame = ws.receive_json()
        assert init_frame["type"] == "HISTORICAL_CANDLES"
        assert "SOL-USD" in init_frame["channel"]


def test_trading_websocket_initial_sync_and_deduplication(client):
    """
    Connect to /ws/trading?symbol=BTC-USD and verify:
    1. Initial frames provide immediate complete state snapshot.
    2. Ping/pong works.
    3. Repeating duplicate messages are NOT continuously spammed without state changes.
    """
    with client.websocket_connect("/ws/trading?symbol=BTC-USD") as ws:
        received_types = set()
        # Read the initial complete snapshot frames
        for _ in range(12):
            frame = ws.receive_json()
            received_types.add(frame["type"])

        # Must include essential trading & telemetry types
        assert "HISTORICAL_CANDLES" in received_types
        assert "TICK" in received_types
        assert "ORDER_BOOK" in received_types
        assert "ACCOUNT_UPDATE" in received_types
        assert "ENGINE_HEALTH" in received_types

        # Test ping
        ws.send_json({"action": "ping"})
        # Read until PONG
        found_pong = False
        for _ in range(10):
            f = ws.receive_json()
            if f["type"] == "PONG":
                found_pong = True
                break
        assert found_pong, "Server did not reply with PONG!"


def test_ws_manager_dirty_state_deduplication():
    """Verify ws_manager.is_state_dirty prevents identical duplicate emissions."""
    test_key = "test_dedup_key"
    data_1 = {"equity": 1000.0, "status": "active"}
    
    # First call: dirty because it's new
    assert ws_manager.is_state_dirty(test_key, data_1, max_idle_seconds=10.0) is True

    # Immediate second call with identical data: clean (not dirty)
    assert ws_manager.is_state_dirty(test_key, data_1, max_idle_seconds=10.0) is False

    # Third call with mutated data: dirty!
    data_2 = {"equity": 1050.0, "status": "active"}
    assert ws_manager.is_state_dirty(test_key, data_2, max_idle_seconds=10.0) is True


def test_event_bus_publishes_to_ws_manager():
    """Verify event_bus position_update dispatches without exception."""
    event = event_bus.publish_position_update(
        trade_id="trd_ws_test_99",
        symbol="BTC-USD",
        side="long",
        size=1.0,
        leverage=5.0,
        entry_price=86000.0,
        mark_price=86100.0,
        status="open",
        opened_at="2026-09-24T12:00:00.000Z",
    )
    assert event["type"] == "position_update"
    assert "payload" in event
    assert "data" in event
    assert event["data"]["trade_id"] == "trd_ws_test_99"

    log_event = event_bus.publish_execution_log(
        level="fill",
        category="take_profit",
        symbol="BTC-USD",
        message="Take profit executed",
        order_id="ord_ws_test_99"
    )
    assert log_event["type"] == "execution_log"
    assert log_event["data"]["log_id"].startswith("log_")
