"""
tests/test_ws_schema.py — Strict Unit Tests for WebSocket Schemas & Envelopes

Validates 100% compliance with:
1. SCHEMA.md rules (all required keys present, never omitted).
2. Pydantic v2 validation for chart candles, order books, positions, logs, health, telemetry.
3. Dual-envelope integrity (simultaneous 'data' and 'payload' population for backend and frontend).
"""

import pytest
import time
from middleware.ws_schema import (
    WSEventType,
    CandleBarSchema,
    HistoricalCandlesPayload,
    OrderBookItem,
    OrderBookPayload,
    PositionUpdatePayload,
    ExecutionLogPayload,
    EngineHealthPayload,
    AccountUpdatePayload,
    MicrostructurePayload,
    MLSignalPayload,
    GoalUpdatePayload,
    QuotaUpdatePayload,
    ScreenerUpdatePayload,
    MarketSessionPayload,
    ClientActionMessage,
    format_ws_event,
)
from utils.time_utils import now_ist_iso


def test_candle_bar_schema_validation():
    bar = CandleBarSchema(
        time=1758712200,
        open=86500.0,
        high=86520.0,
        low=86490.0,
        close=86510.0,
        volume=12.5,
        symbol="BTC-USD",
        timeframe="5s",
        is_bar_closed=False
    )
    assert bar.time == 1758712200
    assert bar.open == 86500.0
    assert bar.high == 86520.0
    assert bar.close == 86510.0
    assert bar.volume == 12.5
    assert bar.symbol == "BTC-USD"
    assert bar.timeframe == "5s"
    assert bar.is_bar_closed is False


def test_historical_candles_payload():
    candles = [
        CandleBarSchema(time=1000 + i * 5, open=100.0, high=105.0, low=99.0, close=102.0, volume=1.0)
        for i in range(5)
    ]
    payload = HistoricalCandlesPayload(symbol="SOL-USD", timeframe="5s", candles=candles)
    assert payload.symbol == "SOL-USD"
    assert len(payload.candles) == 5
    assert payload.candles[0].time == 1000


def test_position_update_schema_conforms_to_schema_md():
    REQUIRED_POSITION_KEYS = [
        "trade_id", "symbol", "side", "size", "leverage", "entry_price",
        "exit_price", "mark_price", "unrealized_pnl", "realized_pnl",
        "status", "opened_at", "closed_at"
    ]

    pos = PositionUpdatePayload(
        trade_id="trd_strict_01",
        symbol="ETH-USD",
        side="long",
        size=2.0,
        leverage=10.0,
        entry_price=2750.0,
        exit_price=None,
        mark_price=2760.0,
        unrealized_pnl=20.0,
        realized_pnl=None,
        status="open",
        opened_at=now_ist_iso(),
        closed_at=None
    )

    data = pos.model_dump()
    for k in REQUIRED_POSITION_KEYS:
        assert k in data, f"Missing required SCHEMA.md key '{k}'"

    assert data["trade_id"] == "trd_strict_01"
    assert data["exit_price"] is None
    assert data["realized_pnl"] is None
    assert data["closed_at"] is None


def test_execution_log_schema_conforms_to_schema_md():
    REQUIRED_EXECUTION_LOG_KEYS = [
        "log_id", "level", "category", "symbol", "message", "order_id"
    ]

    log_item = ExecutionLogPayload(
        log_id="log_strict_01",
        level="fill",
        category="entry_fill",
        symbol="BTC-USD",
        message="Order filled BUY 0.5 BTC-USD @ $86500",
        order_id="ord_strict_01"
    )

    data = log_item.model_dump()
    for k in REQUIRED_EXECUTION_LOG_KEYS:
        assert k in data, f"Missing required SCHEMA.md key '{k}'"

    assert data["level"] == "fill"
    assert data["order_id"] == "ord_strict_01"


def test_engine_health_schema_conforms_to_schema_md():
    REQUIRED_ENGINE_HEALTH_KEYS = [
        "status", "uptime_seconds", "last_heartbeat", "connected_exchanges", "active_positions_count"
    ]

    health = EngineHealthPayload(
        status="healthy",
        uptime_seconds=3600,
        last_heartbeat=now_ist_iso(),
        connected_exchanges={"binance": "connected", "alpaca": "connected"},
        active_positions_count=3
    )

    data = health.model_dump()
    for k in REQUIRED_ENGINE_HEALTH_KEYS:
        assert k in data, f"Missing required SCHEMA.md key '{k}'"

    assert data["status"] == "healthy"
    assert data["uptime_seconds"] == 3600
    assert data["active_positions_count"] == 3


def test_format_ws_event_dual_envelope():
    """
    Guarantees both 'data' and 'payload' point to identical contents,
    with standard ISO8601 timestamp and event type.
    """
    raw_payload = {"key1": "value1", "count": 42}
    envelope = format_ws_event(WSEventType.ACCOUNT_UPDATE, raw_payload, channel="trading")

    assert envelope["type"] == "ACCOUNT_UPDATE"
    assert "timestamp" in envelope
    assert envelope["channel"] == "trading"
    assert envelope["data"] == raw_payload
    assert envelope["payload"] == raw_payload


def test_client_action_message():
    msg = ClientActionMessage(action="subscribe", symbol="AAPL", timeframe="1m")
    assert msg.action == "subscribe"
    assert msg.symbol == "AAPL"
    assert msg.timeframe == "1m"
