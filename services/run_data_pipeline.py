"""
services/run_data_pipeline.py — [DP] Data Pipeline Service

Runnable microservice that:
  1. Fetches OHLCV data via yfinance for all INSTRUMENTS
  2. Computes frac-diff, GARCH vol, RSI, OBI features
  3. Publishes each instrument's feature payload to  tedeng:features

Phase 1 addition:
  4. Subscribes to Binance aggTrade WebSocket for crypto instruments and feeds
     each trade into alpha_overlay.vap_cvd for real-time VAP/CVD tracking.

Usage:
    python services/run_data_pipeline.py
"""

import sys
import os
import json
import time
import logging
import threading

# Project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from data_pipeline.pipeline import DataPipeline
from middleware.broker import Broker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DP-SERVICE] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# BINANCE aggTrade WEBSOCKET  (Phase 1 — crypto CVD/VAP ingestion)
# ─────────────────────────────────────────────────────────────────────────────

# Map config instrument names → Binance stream names
_BINANCE_STREAM_MAP = {
    "BTC-USD": "btcusdt",
    "ETH-USD": "ethusdt",
    "BNB-USD": "bnbusdt",
    "SOL-USD": "solusdt",
    "XRP-USD": "xrpusdt",
}

_RECONNECT_DELAY_S = 5   # seconds to wait before reconnecting after a WS error


def _build_agg_trade_url() -> str | None:
    """
    Build a combined Binance aggTrade stream URL for all configured crypto
    instruments. Returns None if no supported instruments are configured.
    """
    streams = [
        f"{_BINANCE_STREAM_MAP[sym]}@aggTrade"
        for sym in config.CRYPTO_INSTRUMENTS
        if sym in _BINANCE_STREAM_MAP
    ]
    if not streams:
        return None
    stream_path = "/".join(streams)
    return f"wss://stream.binance.com:9443/stream?streams={stream_path}"


# Reverse map: Binance symbol (uppercase) → config instrument name
_BINANCE_TO_CONFIG: dict[str, str] = {
    v.upper() + "T": k          # e.g. "BTCUSDT" → "BTC-USD"
    for k, v in _BINANCE_STREAM_MAP.items()
}


def _run_agg_trade_ws() -> None:
    """
    Background thread: connects to Binance combined aggTrade stream, feeds
    each trade into vap_cvd.ingest_trade(), and auto-reconnects on failure.

    aggTrade message format:
      {"stream": "btcusdt@aggTrade",
       "data": {"e": "aggTrade", "s": "BTCUSDT", "p": "...", "q": "...", "m": true/false}}
      "m" = true  → maker-side was the buyer  → aggressor is a SELL
      "m" = false → maker-side was the seller → aggressor is a BUY
    """
    try:
        from alpha_overlay.vap_cvd import ingest_trade
    except ImportError:
        log.warning("[aggTrade] alpha_overlay.vap_cvd not available; aggTrade feed disabled.")
        return

    url = _build_agg_trade_url()
    if url is None:
        log.info("[aggTrade] No crypto instruments configured — aggTrade feed not started.")
        return

    log.info("[aggTrade] Starting Binance aggTrade WS: %s", url)

    while True:
        try:
            import websocket  # type: ignore  (websocket-client)

            def on_message(ws, raw: str) -> None:
                try:
                    msg = json.loads(raw)
                    data = msg.get("data", {})
                    binance_sym = data.get("s", "")         # e.g. "BTCUSDT"
                    instr = _BINANCE_TO_CONFIG.get(binance_sym)
                    if instr is None:
                        return
                    price = float(data["p"])
                    qty   = float(data["q"])
                    # m=True → buyer is maker → aggressor sold (ask hit)
                    is_agg_buy = not data.get("m", True)
                    ingest_trade(instr, price, qty, is_agg_buy)
                except Exception as exc:
                    log.debug("[aggTrade] parse error: %s", exc)

            def on_error(ws, err) -> None:
                log.warning("[aggTrade] WS error: %s — reconnecting in %ds", err, _RECONNECT_DELAY_S)

            def on_close(ws, code, msg) -> None:
                log.info("[aggTrade] WS closed (code=%s) — reconnecting in %ds", code, _RECONNECT_DELAY_S)

            def on_open(ws) -> None:
                log.info("[aggTrade] Connected to Binance combined stream.")

            ws_app = websocket.WebSocketApp(
                url,
                on_message=on_message,
                on_error=on_error,
                on_close=on_close,
                on_open=on_open,
            )
            ws_app.run_forever(ping_interval=20, ping_timeout=10)

        except ImportError:
            log.warning(
                "[aggTrade] 'websocket-client' not installed. "
                "Run: pip install websocket-client\n"
                "aggTrade feed will not run until the package is available."
            )
            return  # Don't retry on a missing dependency
        except Exception as exc:
            log.error("[aggTrade] Unexpected error: %s", exc)

        log.info("[aggTrade] Waiting %ds before reconnect …", _RECONNECT_DELAY_S)
        time.sleep(_RECONNECT_DELAY_S)


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("Starting TEDENG Data Pipeline Service")
    log.info("Instruments : %s", config.INSTRUMENTS)
    log.info("Poll interval: %ds", config.POLL_INTERVAL_SECONDS)
    log.info("Publishing to channel: %s", config.REDIS_CHANNEL_FEATURES)

    # Launch Binance aggTrade feed in a daemon thread (Phase 1)
    agg_thread = threading.Thread(
        target=_run_agg_trade_ws,
        name="binance-agg-trade",
        daemon=True,
    )
    agg_thread.start()
    log.info("[aggTrade] Feed thread started (daemon).")

    dp = DataPipeline()
    broker = Broker()

    for batch in dp.stream():
        for payload in batch:
            instrument = payload["instrument"]
            # Strip large history arrays from the message for logging clarity
            log_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
            log.info("Publishing features for %s", instrument)
            broker.publish(config.REDIS_CHANNEL_FEATURES, payload)
            log.debug("Payload (no history): %s", json.dumps(log_payload, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Data Pipeline Service stopped by user.")
