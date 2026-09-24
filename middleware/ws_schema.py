"""
middleware/ws_schema.py — Strict WebSocket Event Schemas & Typed Envelopes

Defines canonical Pydantic v2 schemas and envelope formatters for all WebSocket
events across the backend, trading engine, and client gateways.
Guarantees strict schema compliance with SCHEMA.md rules and ensures full
cross-compatibility between frontend consumers and backend testing suites.
"""

from __future__ import annotations
import time
from enum import Enum
from typing import Dict, List, Optional, Any, Union
from pydantic import BaseModel, Field, ConfigDict
from utils.time_utils import ts_to_ist_iso


class WSEventType(str, Enum):
    # System / Liveness
    PING = "PING"
    PONG = "PONG"
    HEARTBEAT = "HEARTBEAT"
    ERROR = "ERROR"

    # Client Actions
    SUBSCRIBE = "SUBSCRIBE"
    UNSUBSCRIBE = "UNSUBSCRIBE"

    # Dedicated Live Chart Stream
    HISTORICAL_CANDLES = "HISTORICAL_CANDLES"
    TICK = "TICK"
    CHART_TICK = "CHART_TICK"

    # Order Book & Microstructure
    ORDER_BOOK = "ORDER_BOOK"
    MICROSTRUCTURE = "MICROSTRUCTURE"

    # Engine Trading & Execution (SCHEMA.md)
    POSITION_UPDATE = "POSITION_UPDATE"
    EXECUTION = "EXECUTION"
    EXECUTION_LOG = "EXECUTION_LOG"
    ML_SIGNAL = "ML_SIGNAL"
    ENGINE_HEALTH = "ENGINE_HEALTH"

    # Account, Quota, Screener & Governance
    ACCOUNT_UPDATE = "ACCOUNT_UPDATE"
    GOAL_UPDATE = "GOAL_UPDATE"
    QUOTA_UPDATE = "QUOTA_UPDATE"
    SCREENER_UPDATE = "SCREENER_UPDATE"
    MARKET_SESSION = "MARKET_SESSION"


class StrictBaseModel(BaseModel):
    model_config = ConfigDict(extra="ignore", populate_by_name=True)


# ── Chart & Tick Schemas ───────────────────────────────────────────────────────

class CandleBarSchema(StrictBaseModel):
    time: int = Field(..., description="Epoch timestamp in seconds")
    open: float = Field(..., description="Opening price")
    high: float = Field(..., description="High price")
    low: float = Field(..., description="Low price")
    close: float = Field(..., description="Closing price")
    volume: float = Field(default=0.0, description="Bar volume")
    symbol: Optional[str] = Field(default=None, description="Instrument ticker")
    timeframe: Optional[str] = Field(default="5s", description="Bar interval (e.g. 1s, 5s, 1m)")
    is_bar_closed: Optional[bool] = Field(default=False, description="Whether the bar period has closed")


class HistoricalCandlesPayload(StrictBaseModel):
    symbol: str = Field(..., description="Instrument ticker symbol")
    timeframe: str = Field(default="5s", description="Bar interval")
    candles: List[CandleBarSchema] = Field(default_factory=list, description="List of historical OHLCV bars")


class OrderBookItem(StrictBaseModel):
    price: float
    size: float
    total: float


class OrderBookPayload(StrictBaseModel):
    symbol: Optional[str] = None
    bids: List[OrderBookItem] = Field(default_factory=list)
    asks: List[OrderBookItem] = Field(default_factory=list)
    spread: float = 0.0


# ── SCHEMA.md Compliant Engine Models ──────────────────────────────────────────

class PositionUpdatePayload(StrictBaseModel):
    """
    Strictly conforms 100% to SCHEMA.md REQUIRED_POSITION_KEYS:
    trade_id, symbol, side, size, leverage, entry_price, exit_price, mark_price,
    unrealized_pnl, realized_pnl, status, opened_at, closed_at.
    """
    trade_id: str
    symbol: str
    side: str
    size: float
    leverage: float
    entry_price: float
    exit_price: Optional[float] = None
    mark_price: float
    unrealized_pnl: Optional[float] = None
    realized_pnl: Optional[float] = None
    status: str
    opened_at: str
    closed_at: Optional[str] = None

    # Optional aliases for UI / legacy store backwards compatibility
    instrument: Optional[str] = None
    qty: Optional[float] = None
    quantity: Optional[float] = None
    current_price: Optional[float] = None
    unrealized_pl: Optional[float] = None
    realized_pl: Optional[float] = None


class ExecutionLogPayload(StrictBaseModel):
    """
    Strictly conforms to SCHEMA.md REQUIRED_EXECUTION_LOG_KEYS:
    log_id, level, category, symbol, message, order_id.
    """
    log_id: str
    level: str
    category: str
    symbol: str
    message: str
    order_id: Optional[str] = None


class EngineHealthPayload(StrictBaseModel):
    """
    Strictly conforms to SCHEMA.md REQUIRED_ENGINE_HEALTH_KEYS:
    status, uptime_seconds, last_heartbeat, connected_exchanges, active_positions_count.
    """
    status: str
    uptime_seconds: int
    last_heartbeat: str
    connected_exchanges: Dict[str, str] = Field(default_factory=dict)
    active_positions_count: int = 0


# ── Account & Telemetry Schemas ───────────────────────────────────────────────

class AccountUpdatePayload(StrictBaseModel):
    equity: float
    balance: Optional[float] = None
    realized_pl: float = 0.0
    gross_buying_power: Optional[float] = None
    active_drawdown_pct: float = 0.0
    positions: Union[Dict[str, Any], List[Dict[str, Any]]] = Field(default_factory=dict)


class MicrostructurePayload(StrictBaseModel):
    symbol: str
    vpoc_price: Optional[float] = None
    vah: Optional[float] = None
    val: Optional[float] = None
    cvd_trend: float = 0.0
    cot_zscore: float = 0.0
    flow_score: float = 0.0
    iff_available: bool = False


class MLSignalPayload(StrictBaseModel):
    signal_id: Optional[str] = None
    instrument: str
    direction_magnitude: float
    confidence_score: float
    conviction_score: Optional[float] = None
    regime_flag: Optional[str] = None
    latency_ms: Optional[float] = None
    features: Optional[Dict[str, Any]] = None
    ohlcv: Optional[Dict[str, Any]] = None


class GoalUpdatePayload(StrictBaseModel):
    monthly_target_usd: float = 100.0
    monthly_pnl_usd: float = 0.0
    monthly_pnl_pct: float = 0.0
    crypto_trades_used: Optional[str] = "0/20"
    stock_trades_used: Optional[str] = "0/80"
    crypto_completed: Optional[int] = 0
    crypto_ceiling: Optional[int] = 20
    stock_completed: Optional[int] = 0
    stock_ceiling: Optional[int] = 80
    equity_current_usd: Optional[float] = 1000.0
    equity_peak_usd: Optional[float] = 1000.0
    current_drawdown_pct: Optional[float] = 0.0
    engine_paused: bool = False
    pause_reason: Optional[str] = None


class QuotaUpdatePayload(StrictBaseModel):
    crypto: Optional[Dict[str, Any]] = None
    futures: Optional[Dict[str, Any]] = None


class ScreenerUpdatePayload(StrictBaseModel):
    long: str = "PENDING"
    short: str = "PENDING"
    timestamp: Union[float, int, str] = 0


class MarketSessionPayload(StrictBaseModel):
    us: Optional[Dict[str, Any]] = None
    crypto: Optional[Dict[str, Any]] = None
    current_symbol: Optional[Dict[str, Any]] = None


# ── Client Inbound Messages ───────────────────────────────────────────────────

class ClientActionMessage(StrictBaseModel):
    action: str = Field(..., description="Action type: subscribe, unsubscribe, ping")
    symbol: Optional[str] = Field(default=None, description="Instrument symbol (e.g. BTC-USD)")
    channel: Optional[str] = Field(default=None, description="Target channel")
    timeframe: Optional[str] = Field(default="5s", description="Candle resolution")


# ── Envelope Formatter ─────────────────────────────────────────────────────────

def format_ws_event(
    event_type: Union[WSEventType, str],
    payload: Any,
    channel: Optional[str] = None,
    timestamp: Optional[str] = None,
) -> dict:
    """
    Constructs a canonical, strict WebSocket envelope.
    Populates both 'data' and 'payload' so tests checking 'data' (SCHEMA.md)
    and frontend listeners expecting 'payload' operate seamlessly with zero mismatch.
    """
    type_str = event_type.value if isinstance(event_type, Enum) else str(event_type)
    ts = timestamp or ts_to_ist_iso(time.time())

    # If payload is a Pydantic model, convert to dict
    if isinstance(payload, BaseModel):
        data_dict = payload.model_dump()
    elif isinstance(payload, list):
        data_dict = [item.model_dump() if isinstance(item, BaseModel) else item for item in payload]
    elif isinstance(payload, dict):
        data_dict = dict(payload)
    else:
        data_dict = payload

    envelope: dict = {
        "type": type_str,
        "timestamp": ts,
        "data": data_dict,
        "payload": data_dict,
    }

    if channel:
        envelope["channel"] = channel

    return envelope
