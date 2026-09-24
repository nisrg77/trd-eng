# TRDENG Structured Event & API Schema Specification (`SCHEMA.md`)

This document defines the authoritative, strictly-typed event schemas for the TRDENG Execution Engine, WebSocket Gateway (`/ws/trading`), and REST API Endpoints (`/api/engine-health`, `/api/positions`, `/api/trade-logs`).

---

## Guaranteed Formatting Rules
1. **No Omitted Keys**: Every schema field is **always present**. When a field is not applicable for a given state (e.g. `exit_price` on an open trade), it MUST be set to `null` — never omitted or left `undefined`.
2. **ISO8601 Timestamps**: All timestamp strings MUST use UTC ISO8601 format (e.g. `2026-09-23T14:52:00.000Z`).
3. **Decoupled Event Types**:
   - `position_update`: Structured position & trade lifecycle updates.
   - `execution_log`: Human-readable system & execution log telemetry.
   - `engine_health`: Engine runtime telemetry & heartbeat.

---

## 1. WebSocket & API Event Schemas

### Event 1: `position_update`
Emitted whenever a position is opened, updated on mark-price tick, partially closed, fully closed, or liquidated.

```json
{
  "type": "position_update",
  "timestamp": "2026-09-23T14:52:00.000Z",
  "data": {
    "trade_id": "trd_8f1a92b4",
    "symbol": "BTC-USD",
    "side": "long",
    "size": 0.45,
    "leverage": 10.0,
    "entry_price": 86500.0,
    "exit_price": null,
    "mark_price": 86750.5,
    "unrealized_pnl": 112.72,
    "realized_pnl": null,
    "status": "open",
    "opened_at": "2026-09-23T14:30:00.000Z",
    "closed_at": null
  }
}
```

#### Field Specifications: `position_update.data`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `trade_id` | `string` | Unique UUID for the position lifecycle. |
| `symbol` | `string` | Symbol identifier (e.g. `"BTC-USD"`, `"AAPL"`). |
| `instrument` | `string` | Canonical instrument identifier (synonym for `symbol`). |
| `side` | `"long"` \| `"short"` | Position direction (`"long"` for positive qty, `"short"` for negative qty). |
| `size` | `number` | Absolute quantity of contracts / shares (`> 0`). |
| `qty` | `number` | Signed position quantity (`> 0` for long, `< 0` for short, micro precision up to 6 decimals for crypto). |
| `leverage` | `number` | Applied leverage factor (e.g. `10.0`). |
| `entry_price` | `number` | Weighted average fill price on entry. |
| `exit_price` | `number` \| `null` | Fill price on exit (`null` while position is `"open"`). |
| `mark_price` | `number` | Current mark-to-market price. |
| `current_price` | `number` | Real-time mark price (synonym for `mark_price`). |
| `unrealized_pnl` | `number` | Pure mark-to-market P&L: `(mark_price - entry_price) * size * (1 if side == "long" else -1)`. |
| `realized_pnl` | `number` \| `null` | Booked P&L upon partial or total exit (`null` if fully open without prior exit). |
| `status` | `"open"` \| `"closed"` \| `"liquidated"` | Current trade lifecycle state. |
| `opened_at` | `string` (ISO8601) | ISO8601 UTC timestamp when trade opened. |
| `closed_at` | `string` (ISO8601) \| `null` | ISO8601 UTC timestamp when trade closed (`null` while `"open"`). |

---

### Event 2: `execution_log`
Emitted for human-readable execution audit logs, decoupled from structured trade state updates.

```json
{
  "type": "execution_log",
  "timestamp": "2026-09-23T14:52:00.000Z",
  "data": {
    "log_id": "log_a1b2c3d4",
    "level": "info",
    "category": "fill",
    "symbol": "BTC-USD",
    "message": "TP1 Triggered for LONG BTC-USD @ 86750.50 (realized PnL: +$45.00)",
    "order_id": "ord_9f8e7d6c"
  }
}
```

#### Field Specifications: `execution_log.data`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `log_id` | `string` | Unique identifier for log message. |
| `level` | `"info"` \| `"warn"` \| `"error"` \| `"fill"` | Log severity / type. |
| `category` | `string` | Category (e.g. `"fill"`, `"risk_guard"`, `"session"`). |
| `symbol` | `string` | Associated instrument symbol (e.g. `"BTC-USD"`). |
| `message` | `string` | Human-readable log details. |
| `order_id` | `string` \| `null` | Associated order ID if applicable (`null` otherwise). |

---

### Event 3: `engine_health`
Emitted periodically over WebSocket and returned by REST endpoint `GET /api/engine-health`.

```json
{
  "type": "engine_health",
  "timestamp": "2026-09-23T14:52:00.000Z",
  "data": {
    "status": "healthy",
    "uptime_seconds": 3600,
    "last_heartbeat": "2026-09-23T14:52:00.000Z",
    "connected_exchanges": {
      "binance": "connected",
      "alpaca": "connected"
    },
    "active_positions_count": 2
  }
}
```

#### Field Specifications: `engine_health.data`
| Field Name | Type | Description |
| :--- | :--- | :--- |
| `status` | `"healthy"` \| `"degraded"` \| `"error"` | Engine health status. |
| `uptime_seconds` | `number` | Uptime in seconds. |
| `last_heartbeat` | `string` (ISO8601) | Timestamp of last heartbeat. |
| `connected_exchanges` | `object` | Connection status per feed provider. |
| `active_positions_count` | `number` | Count of currently open positions. |

---

## 2. REST API Endpoints

### `GET /api/engine-health`
Returns current engine status conforming to `engine_health.data`.

### `GET /api/positions`
Returns an array of all current active positions conforming to `position_update.data`.

### `GET /api/trade-logs`
Returns recent structured execution logs conforming to `execution_log.data`.

### `GET /api/klines?symbol={symbol}&limit={limit}`
Returns an array of historical OHLCV candlestick bars for TradingView chart rendering.

### `GET /api/screener/top-stocks`
Returns the ranked CME SSF top stock candidates sourced via the TradingView Screener batch scan.

---

## 3. Dedicated Live Chart WebSocket (`/ws/charts` & `/ws/chart`)

High-frequency, low-latency streaming endpoint dedicated strictly to real-time charting (TradingView / Lightweight Charts). Completely decoupled from order routing, risk gating, and heavy account state.

- **URL**: `ws://{host}:8000/ws/charts?symbol={symbol}&timeframe={timeframe}`
- **Default Parameters**: `symbol=BTC-USD`, `timeframe=5s` (supports `1s`, `5s`, `15s`, `1m`)

### 3.1 Initial Frame (`HISTORICAL_CANDLES`)
Emitted immediately upon client connection:
```json
{
  "type": "HISTORICAL_CANDLES",
  "timestamp": "2026-09-24T12:00:00.000Z",
  "channel": "chart:BTC-USD:5s",
  "data": [
    {"time": 1758712175, "open": 86500.0, "high": 86510.0, "low": 86495.0, "close": 86505.0, "volume": 12.5, "symbol": "BTC-USD", "timeframe": "5s", "is_bar_closed": true}
  ],
  "payload": [
    {"time": 1758712175, "open": 86500.0, "high": 86510.0, "low": 86495.0, "close": 86505.0, "volume": 12.5}
  ]
}
```

### 3.2 Streaming Tick Frame (`TICK`)
Emitted at ~250ms cadence:
```json
{
  "type": "TICK",
  "timestamp": "2026-09-24T12:00:05.000Z",
  "channel": "chart:BTC-USD:5s",
  "data": {
    "time": 1758712200,
    "open": 86505.0,
    "high": 86515.0,
    "low": 86502.0,
    "close": 86512.0,
    "volume": 3.4,
    "symbol": "BTC-USD",
    "timeframe": "5s",
    "is_bar_closed": false
  },
  "payload": {
    "time": 1758712200,
    "open": 86505.0,
    "high": 86515.0,
    "low": 86502.0,
    "close": 86512.0,
    "volume": 3.4
  }
}
```

### 3.3 Inbound Client Actions
- **Ping / Keep-alive**: `{"action": "ping"}` -> Returns `{"type": "PONG", "data": {"status": "ok"}}`
- **Dynamic Symbol Switch**: `{"action": "subscribe", "symbol": "ETH-USD", "timeframe": "5s"}` -> Instantly switches active stream and returns new `HISTORICAL_CANDLES`.

---

## 4. Unified Trading & Engine Gateway (`/ws/trading`)

Comprehensive telemetry and execution socket with intelligent deduplication:
- Emits real-time ticks, order book, and engine execution events.
- State telemetry (`ACCOUNT_UPDATE`, `GOAL_UPDATE`, `QUOTA_UPDATE`, `SCREENER_UPDATE`, `MARKET_SESSION`, `ENGINE_HEALTH`) is dirty-checked and only transmitted when mutations occur or upon a periodic 5–10s heartbeat.
- Eliminates repeated duplicate frames and redundant disk reads.

