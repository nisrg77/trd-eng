import asyncio
import json
import os
import random
import time
import requests
from typing import Optional, Dict, Any, List
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Depends, HTTPException, Body
from fastapi.middleware.cors import CORSMiddleware

# ── IFF / Microstructure overlay imports (graceful degradation if not yet wired) ──
try:
    import sys as _sys
    import os as _os
    _BASE = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _BASE not in _sys.path:
        _sys.path.insert(0, _BASE)
    from alpha_overlay.vap_cvd import get_vpoc, get_vah_val, get_cvd
    from alpha_overlay.iff import get_flow_score
    from alpha_overlay.cot_bias import get_cot_zscore
    _IFF_AVAILABLE = True
except Exception:
    _IFF_AVAILABLE = False

    def get_vpoc(s):                    return None     # type: ignore
    def get_vah_val(s, p=None):         return None     # type: ignore
    def get_cvd(s):                     return 0.0      # type: ignore
    def get_flow_score(s, r=0.0):       return 0.0      # type: ignore
    def get_cot_zscore(s):              return 0.0      # type: ignore

import logging
from utils.time_utils import now_ist
logging.basicConfig(level=logging.INFO, format="%(asctime)s [WS] %(levelname)s %(message)s", datefmt="%H:%M:%S")
logging.Formatter.converter = lambda *args: now_ist().timetuple()
log = logging.getLogger(__name__)

from middleware.ws_schema import WSEventType, format_ws_event, ClientActionMessage
from middleware.ws_manager import ws_manager
from services.chart_feed import chart_feed_manager

app = FastAPI(title="TEDENG ML Engine WebSocket Server")

@app.on_event("startup")
async def startup_event():
    try:
        loop = asyncio.get_running_loop()
        ws_manager.set_loop(loop)
    except Exception:
        pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

import sys

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

ACCOUNT_FILE = os.path.join(BASE_DIR, "simulated_account.json")
SIGNALS_FILE = os.path.join(BASE_DIR, "signals_store.json")
EXECUTIONS_FILE = os.path.join(BASE_DIR, "execution_store.json")

_json_cache: dict[str, tuple[float, any]] = {}

def read_json_safe(filepath, default=None):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

def read_json_cached(filepath, ttl: float = 1.0, default=None):
    now = time.time()
    if filepath in _json_cache:
        ts, cached_data = _json_cache[filepath]
        if now - ts < ttl:
            return cached_data
    val = read_json_safe(filepath, default=default)
    _json_cache[filepath] = (now, val)
    return val

def generate_mock_order_book(current_price):
    bids = []
    asks = []
    base = current_price or 100.0
    
    # Scale tick step based on asset price (crypto vs equities)
    if base > 10000:
        step = 1.5
    elif base > 1000:
        step = 0.25
    elif base > 100:
        step = 0.05
    else:
        step = 0.01

    noise = step * 0.1
    cum_bid = 0.0
    cum_ask = 0.0
    for i in range(1, 11):
        bp = round(base - (i * step) + random.uniform(-noise, noise), 2)
        bs = round(random.uniform(0.1, 2.5), 4)
        cum_bid += bs
        bids.append({"price": bp, "size": bs, "total": round(cum_bid, 4)})

        ap = round(base + (i * step) + random.uniform(-noise, noise), 2)
        as_size = round(random.uniform(0.1, 2.5), 4)
        cum_ask += as_size
        asks.append({"price": ap, "size": as_size, "total": round(cum_ask, 4)})

    return {
        "bids": bids,
        "asks": asks,
        "spread": round(max(0.01, asks[0]["price"] - bids[0]["price"]), 2)
    }

DEFAULT_PRICES = {
    "BTC-USD": 86600.0,
    "ETH-USD": 2755.0,
    "AAPL": 341.0,
    "SPY": 774.0,
    "NVDA": 138.5,
    "TSLA": 252.0,
    "META": 585.0,
    "MSFT": 435.0,
    "AMZN": 190.0,
    "GOOGL": 168.0,
    "AMD": 155.0,
    "JPM": 222.0,
    "DIS": 96.0,
    "INTC": 22.5,
    "NKE": 82.0,
    "PFE": 28.5,
    "PYPL": 78.0,
}

_price_cache: dict[str, tuple[float, float]] = {}

def fetch_symbol_last_price(symbol: str) -> float:
    now = time.time()
    if symbol in _price_cache:
        cached_p, ts = _price_cache[symbol]
        if now - ts < 5.0:
            return cached_p

    # 1. Check active positions
    account = read_json_safe(ACCOUNT_FILE, default={})
    if symbol in account.get("positions", {}):
        p = account["positions"][symbol].get("current_price") or account["positions"][symbol].get("entry_price")
        if p and p > 0:
            _price_cache[symbol] = (float(p), now)
            return float(p)

    # 2. Check latest signals
    signals = read_json_safe(SIGNALS_FILE, default={})
    if symbol in signals and signals[symbol]:
        c = signals[symbol][-1].get("ohlcv", {}).get("close")
        if c and float(c) > 0:
            _price_cache[symbol] = (float(c), now)
            return float(c)

    # 3. Real-time Crypto via Binance API
    if any(c in symbol for c in ["BTC", "ETH", "SOL", "BNB", "XRP"]):
        try:
            binance_sym = symbol.replace("-USD", "USDT").replace("-", "").upper()
            resp = requests.get(f"https://api.binance.com/api/v3/ticker/price?symbol={binance_sym}", timeout=1.5)
            if resp.status_code == 200:
                live_p = float(resp.json().get("price", 0.0))
                if live_p > 0:
                    _price_cache[symbol] = (live_p, now)
                    return live_p
        except Exception:
            pass

    # 4. Real-time US Stocks via TradingView Screener
    try:
        from tradingview_screener import stocks, col
        clean_sym = symbol.replace("-USD", "").upper()
        count, df = stocks().select("name", "close").where(col("name").isin([clean_sym])).get_scanner_data()
        if df is not None and not df.empty:
            tv_p = float(df["close"].iloc[0])
            if tv_p > 0:
                _price_cache[symbol] = (tv_p, now)
                return tv_p
    except Exception:
        pass

    fallback = DEFAULT_PRICES.get(symbol, 150.0)
    _price_cache[symbol] = (fallback, now)
    return fallback

def _format_screener_response(cache_data):
    candidates = cache_data.get("top_candidates", cache_data.get("candidates", []))
    last_updated = cache_data.get("last_updated", cache_data.get("timestamp", ""))
    ttl_days = cache_data.get("ttl_days", 7)
    age_days = 0.0
    if last_updated:
        try:
            if isinstance(last_updated, (int, float)):
                age_days = (time.time() - float(last_updated)) / 86400.0
            else:
                from datetime import datetime, timezone
                dt = datetime.fromisoformat(str(last_updated).replace("Z", "+00:00"))
                age_days = (datetime.now(timezone.utc) - dt).total_seconds() / 86400.0
        except Exception:
            age_days = 0.0
    return {
        "timestamp": last_updated,
        "next_refresh": cache_data.get("expires_at", ""),
        "cache_age_days": round(age_days, 2),
        "ttl_days": ttl_days,
        "count": len(candidates),
        "source": cache_data.get("source", "cache"),
        "candidates": candidates,
        "top_candidates": candidates
    }

@app.get("/api/screener/top-stocks")
def get_screener_top_stocks():
    cache_path = os.path.join(BASE_DIR, "screener_cache.json")
    cache_data = read_json_safe(cache_path, default=None)
    if not cache_data:
        from data_pipeline.stock_screener import stock_screener
        candidates = stock_screener.get_top_candidates(count=15)
        cache_data = read_json_safe(cache_path, default={"top_candidates": candidates})
    return _format_screener_response(cache_data)

@app.post("/api/screener/refresh")
def refresh_screener():
    from data_pipeline.stock_screener import stock_screener
    candidates = stock_screener.get_top_candidates(count=15, force_refresh=True)
    cache_path = os.path.join(BASE_DIR, "screener_cache.json")
    cache_data = read_json_safe(cache_path, default={"top_candidates": candidates})
    return _format_screener_response(cache_data)

@app.get("/api/stocks/search")
def search_stocks(q: str = ""):
    q = q.upper().strip()
    from data_pipeline.stock_screener import CME_SSF_55_PROXIES
    all_tickers = sorted(list(set(CME_SSF_55_PROXIES + ["AMD", "COIN", "PLTR", "BABA", "NFLX", "UBER", "ARM", "SMCI", "QQQ"])))
    if not q:
        matches = all_tickers[:10]
    else:
        matches = [t for t in all_tickers if q in t][:10]
    results = []
    for sym in matches:
        results.append({
            "symbol": sym,
            "name": f"{sym} SSF Proxy",
            "type": "US_STOCK_FUTURE",
            "price": fetch_symbol_last_price(sym)
        })
    return {"query": q, "results": results}

@app.get("/api/market-sessions")
def get_market_sessions():
    from execution.market_session import get_market_sessions_summary
    return get_market_sessions_summary()

@app.get("/api/engine-health")
def get_engine_health():
    from middleware.event_bus import event_bus
    return event_bus.get_engine_health()

@app.get("/api/positions")
def get_positions():
    from middleware.db_manager import mongo_db
    if mongo_db.is_connected():
        mongo_pos = mongo_db.get_active_positions()
        if mongo_pos:
            return {"positions": list(mongo_pos.values())}
    from middleware.event_bus import event_bus
    return {"positions": event_bus.get_active_positions()}

@app.get("/api/trade-logs")
def get_trade_logs():
    from middleware.db_manager import mongo_db
    if mongo_db.is_connected():
        mongo_logs = mongo_db.get_trade_logs()
        if mongo_logs:
            return {"logs": mongo_logs}
    from middleware.event_bus import event_bus
    return {"logs": event_bus.get_execution_logs()}

@app.get("/api/decision-traces")
def get_decision_traces(limit: int = 100):
    from core.decision_trace import decision_trace_buffer
    return {"traces": decision_trace_buffer.get_recent_traces(limit=limit)}

# ── Institutional Strategy Governance & Promotion Endpoints ───────────────────
from services.auth_middleware import require_admin_auth
from goals.hardened_risk_guard import hardened_risk_guard
from middleware.strategy_promotion import promotion_manager

@app.post("/api/reset-paper-trading")
def reset_paper_trading_api(admin_key: str = Depends(require_admin_auth)):
    try:
        import subprocess
        script_path = os.path.join(BASE_DIR, "scripts", "reset_paper_trading.py")
        result = subprocess.run([sys.executable, script_path], capture_output=True, text=True)
        return {"status": "success", "message": "Paper trading state successfully reset to $1000 equity.", "output": result.stdout}
    except Exception as e:
        return {"status": "error", "message": str(e)}

@app.get("/api/strategies")
def list_strategies(asset_class: Optional[str] = None):
    from middleware.db_manager import mongo_db
    strats = mongo_db.list_strategies(asset_class=asset_class)
    # Merge promotion stage information
    enriched = []
    for s in strats:
        rec = promotion_manager.get_strategy_record(s["strategy_id"])
        s_copy = dict(s)
        s_copy["promotion_stage"] = rec["stage"] if rec else "RESEARCH"
        s_copy["authorized_for_live"] = promotion_manager.is_authorized_for_live(s["strategy_id"]) if rec else False
        enriched.append(s_copy)
    return {"strategies": enriched}

@app.get("/api/strategies/{strategy_id}")
def get_strategy_details(strategy_id: str):
    from middleware.db_manager import mongo_db
    strat = mongo_db.get_strategy(strategy_id)
    rec = promotion_manager.get_strategy_record(strategy_id)
    return {
        "strategy": strat,
        "governance_record": rec,
        "authorized_for_live": promotion_manager.is_authorized_for_live(strategy_id) if rec else False
    }

@app.post("/api/strategies/{strategy_id}/toggle")
def toggle_strategy_status(
    strategy_id: str,
    payload: dict = Body(...),
    admin_key: str = Depends(require_admin_auth)
):
    target_status = payload.get("status", "active")
    from middleware.db_manager import mongo_db
    
    # If enabling live execution, check promotion authorization
    if target_status == "active":
        rec = promotion_manager.get_strategy_record(strategy_id)
        # If in paper/dry-run, allow; but if attempting live, block unless authorized
        is_live_attempt = payload.get("mode") == "live"
        if is_live_attempt and not promotion_manager.is_authorized_for_live(strategy_id):
            raise HTTPException(
                status_code=403,
                detail=f"Strategy '{strategy_id}' is not authorized for LIVE trading (Stage: {rec['stage'] if rec else 'UNREGISTERED'}). Must complete promotion pipeline."
            )
            
    mongo_db.update_strategy_status(strategy_id, target_status)
    return {"status": "success", "strategy_id": strategy_id, "new_status": target_status}

@app.post("/api/strategies/{strategy_id}/promote")
def promote_strategy_to_live(
    strategy_id: str,
    payload: dict = Body(...),
    admin_key: str = Depends(require_admin_auth)
):
    approver_name = payload.get("approver_name", "RiskAdmin")
    approver_role = payload.get("approver_role", "Trading Head")
    reason = payload.get("reason", "Manual live trading authorization")

    ok, msg = promotion_manager.approve_for_live(strategy_id, approver_name, approver_role, reason)
    if not ok:
        raise HTTPException(status_code=400, detail=msg)
    return {"status": "success", "message": msg, "record": promotion_manager.get_strategy_record(strategy_id)}

# ── Institutional Risk Guard & Kill Switch Endpoints ─────────────────────────
@app.get("/api/risk/status")
def get_risk_status():
    return {
        "kill_switch_active": hardened_risk_guard.is_kill_switch_active,
        "max_monthly_loss_usd": hardened_risk_guard.max_monthly_loss_usd,
        "max_position_size_usd": hardened_risk_guard.max_position_size_usd,
        "max_gross_exposure_usd": hardened_risk_guard.max_gross_exposure_usd,
        "daily_trade_limits": hardened_risk_guard.daily_trade_limits
    }

@app.post("/api/risk/kill-switch")
def trigger_kill_switch(
    payload: dict = Body(default={"reason": "Manual operator kill switch"}),
    admin_key: str = Depends(require_admin_auth)
):
    reason = payload.get("reason", "Manual operator kill switch")
    hardened_risk_guard.trigger_emergency_kill_switch(reason)
    return {"status": "HALTED", "message": "Emergency kill switch ACTIVATED. All new entries frozen.", "reason": reason}

@app.post("/api/risk/kill-switch/reset")
def reset_kill_switch(
    admin_key: str = Depends(require_admin_auth)
):
    hardened_risk_guard.reset_kill_switch()
    return {"status": "ARMED", "message": "Emergency kill switch RESET. Normal trading operations permitted."}

@app.get("/api/klines")
def get_klines(symbol: str = "BTC-USD", limit: int = 50):
    p = fetch_symbol_last_price(symbol)
    now_sec = (int(time.time()) // 5) * 5
    history = []
    for i in range(limit, 0, -1):
        t = now_sec - (i * 5)
        var = max(0.02, p * 0.0003)
        o = round(p + random.uniform(-var, var), 2)
        h = round(max(o, p) + random.uniform(0.01, var), 2)
        l = round(min(o, p) - random.uniform(0.01, var), 2)
        c = round(p, 2)
        v = round(random.uniform(5.0, 100.0), 2)
        history.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
        p = c
    return {"symbol": symbol, "candles": history}

# ── Dedicated Live Chart WebSocket (/ws/charts & /ws/chart) ───────────────────
@app.websocket("/ws/charts")
@app.websocket("/ws/chart")
async def live_chart_websocket(websocket: WebSocket, symbol: str = "BTC-USD", timeframe: str = "5s"):
    """
    Dedicated high-frequency WebSocket for real-time charting (Lightweight Charts / TradingView).
    Completely isolated from portfolio, risk, or execution I/O.
    Supports instant historical candle bootstrapping, live tick/bar streaming,
    and runtime symbol/timeframe switching.
    """
    await websocket.accept()
    active_symbol = symbol.upper().strip()

    # Parse timeframe seconds
    tf_seconds = 5
    if timeframe.endswith("s"):
        try:
            tf_seconds = max(1, int(timeframe[:-1]))
        except Exception:
            tf_seconds = 5
    elif timeframe.endswith("m"):
        try:
            tf_seconds = max(60, int(timeframe[:-1]) * 60)
        except Exception:
            tf_seconds = 60

    channel = f"chart:{active_symbol}:{timeframe}"
    client_id = await ws_manager.connect(websocket, client_type="chart", initial_channels=[channel])
    log.info("[WS-Chart] Connected %s (symbol=%s, timeframe=%s)", client_id, active_symbol, timeframe)

    try:
        # 1. Immediately send initial historical candles for instant chart render
        base_p = fetch_symbol_last_price(active_symbol)
        candles = chart_feed_manager.get_initial_candles(
            active_symbol, base_price=base_p, count=50, timeframe_seconds=tf_seconds
        )
        await websocket.send_json(format_ws_event(
            WSEventType.HISTORICAL_CANDLES,
            candles,
            channel=channel
        ))

        # 2. Main chart streaming and client action loop
        last_tick_time = 0.0

        while True:
            # Check for inbound client messages (subscribe, switch, ping)
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.25)
                action = str(msg.get("action", "")).lower()

                if action == "ping":
                    await websocket.send_json(format_ws_event(
                        WSEventType.PONG,
                        {"status": "ok", "time": time.time()},
                        channel=channel
                    ))

                elif action in ["subscribe", "switch"]:
                    new_sym = msg.get("symbol", "").upper().strip()
                    new_tf = msg.get("timeframe", timeframe)
                    if new_sym and (new_sym != active_symbol or new_tf != timeframe):
                        await ws_manager.unsubscribe(websocket, channel)
                        active_symbol = new_sym
                        timeframe = new_tf
                        if timeframe.endswith("s"):
                            try:
                                tf_seconds = max(1, int(timeframe[:-1]))
                            except Exception:
                                tf_seconds = 5
                        elif timeframe.endswith("m"):
                            try:
                                tf_seconds = max(60, int(timeframe[:-1]) * 60)
                            except Exception:
                                tf_seconds = 60
                        channel = f"chart:{active_symbol}:{timeframe}"
                        await ws_manager.subscribe(websocket, channel)

                        new_base = fetch_symbol_last_price(active_symbol)
                        new_candles = chart_feed_manager.get_initial_candles(
                            active_symbol, base_price=new_base, count=50, timeframe_seconds=tf_seconds
                        )
                        await websocket.send_json(format_ws_event(
                            WSEventType.HISTORICAL_CANDLES,
                            new_candles,
                            channel=channel
                        ))

                elif action == "unsubscribe":
                    await ws_manager.unsubscribe(websocket, channel)

            except asyncio.TimeoutError:
                pass

            # Stream live tick bar (~250ms cadence)
            now = time.time()
            if now - last_tick_time >= 0.25:
                last_tick_time = now
                live_price = fetch_symbol_last_price(active_symbol)
                tick_data = chart_feed_manager.generate_simulated_tick(
                    active_symbol, base_price=live_price, timeframe_seconds=tf_seconds
                )
                await websocket.send_json(format_ws_event(
                    WSEventType.TICK,
                    tick_data,
                    channel=channel
                ))

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
        log.info("[WS-Chart] Disconnected %s", client_id)
    except Exception as e:
        log.debug("[WS-Chart] Exception for %s: %s", client_id, e)
        await ws_manager.disconnect(websocket)


# ── Unified Engine & Trading Telemetry WebSocket (/ws/trading) ────────────────
@app.websocket("/ws/trading")
async def websocket_endpoint(websocket: WebSocket, symbol: str = "BTC-USD"):
    """
    Unified engine execution and telemetry gateway.
    Emits real-time ticks, state updates, ML signals, and position lifecycle events.
    Applies strict deduplication to eliminate redundant, repeating frames.
    """
    await websocket.accept()
    active_symbol = symbol.upper().strip()
    trading_channel = "trading"
    chart_channel = f"chart:{active_symbol}:5s"

    client_id = await ws_manager.connect(
        websocket, client_type="trading", initial_channels=[trading_channel, chart_channel]
    )
    log.info("[WS-Trading] Client %s connected (symbol=%s)", client_id, active_symbol)

    # Initialize baseline signal and execution counters to avoid replaying stale historical files
    signals_init = read_json_cached(SIGNALS_FILE, ttl=1.0, default={})
    last_signal_count = len(signals_init.get(active_symbol, []))
    exec_init = read_json_cached(EXECUTIONS_FILE, ttl=1.0, default=[])
    last_exec_count = len(exec_init) if isinstance(exec_init, list) else 0

    try:
        # 1. Send initial historical candles for immediate chart rendering
        current_price = fetch_symbol_last_price(active_symbol)
        candles = chart_feed_manager.get_initial_candles(
            active_symbol, base_price=current_price, count=50, timeframe_seconds=5
        )
        await websocket.send_json(format_ws_event(
            WSEventType.HISTORICAL_CANDLES,
            candles,
            channel=chart_channel
        ))

        # Lazy imports for telemetry modules
        from middleware.db_manager import mongo_db
        from middleware.event_bus import event_bus
        from goals.goal_module import monthly_progress_summary
        from execution.market_session import is_market_session_open, get_market_sessions_summary

        first_loop = True

        while True:
            # Inbound command handling (ping, subscribe, unsubscribe)
            try:
                msg = await asyncio.wait_for(websocket.receive_json(), timeout=0.5)
                action = str(msg.get("action", "")).lower()

                if action == "ping":
                    await websocket.send_json(format_ws_event(
                        WSEventType.PONG,
                        {"status": "ok", "time": time.time()}
                    ))
                elif action in ["subscribe", "switch"]:
                    new_sym = msg.get("symbol", "").upper().strip()
                    if new_sym and new_sym != active_symbol:
                        await ws_manager.unsubscribe(websocket, chart_channel)
                        active_symbol = new_sym
                        chart_channel = f"chart:{active_symbol}:5s"
                        await ws_manager.subscribe(websocket, chart_channel)

                        current_price = fetch_symbol_last_price(active_symbol)
                        candles = chart_feed_manager.get_initial_candles(
                            active_symbol, base_price=current_price, count=50, timeframe_seconds=5
                        )
                        await websocket.send_json(format_ws_event(
                            WSEventType.HISTORICAL_CANDLES,
                            candles,
                            channel=chart_channel
                        ))
            except asyncio.TimeoutError:
                pass

            # 1. Live Tick
            current_price = fetch_symbol_last_price(active_symbol)
            tick_data = chart_feed_manager.generate_simulated_tick(
                active_symbol, base_price=current_price, timeframe_seconds=5
            )
            await websocket.send_json(format_ws_event(WSEventType.TICK, tick_data))

            # 2. Live Order Book
            order_book = generate_mock_order_book(tick_data["close"])
            await websocket.send_json(format_ws_event(WSEventType.ORDER_BOOK, order_book))

            # 3. Read account state (deduplicated: only sent when changed or on heartbeat)
            account = None
            if mongo_db.is_connected():
                account = mongo_db.get_account()
                if account:
                    account["positions"] = mongo_db.get_active_positions()
            if not account:
                account = read_json_cached(ACCOUNT_FILE, ttl=1.0, default={
                    "equity": 1000.0,
                    "realized_pl": 0.0,
                    "positions": {}
                })

            if first_loop or ws_manager.is_state_dirty(f"account_{client_id}", account, max_idle_seconds=5.0):
                await websocket.send_json(format_ws_event(WSEventType.ACCOUNT_UPDATE, account))

            # 4. ML Signals (stream newly arrived signals)
            signals_data = read_json_cached(SIGNALS_FILE, ttl=1.0, default={})
            symbol_signals = signals_data.get(active_symbol, [])
            if len(symbol_signals) > last_signal_count:
                new_signals = symbol_signals[last_signal_count:]
                for sig in new_signals:
                    await websocket.send_json(format_ws_event(WSEventType.ML_SIGNAL, sig))
                last_signal_count = len(symbol_signals)

            # 5. Executions (stream newly arrived executions)
            exec_list = read_json_cached(EXECUTIONS_FILE, ttl=1.0, default=[])
            if isinstance(exec_list, list) and len(exec_list) > last_exec_count:
                new_execs = exec_list[last_exec_count:]
                for ex in new_execs:
                    await websocket.send_json(format_ws_event(WSEventType.EXECUTION, ex))
                last_exec_count = len(exec_list)

            # 6. Goal & Quota updates (deduplicated: avoids repetitive spamming)
            goal_summary = monthly_progress_summary()
            if first_loop or ws_manager.is_state_dirty(f"goal_{client_id}", goal_summary, max_idle_seconds=5.0):
                await websocket.send_json(format_ws_event(WSEventType.GOAL_UPDATE, goal_summary))

            raw_goal_state = read_json_cached(os.path.join(BASE_DIR, "quota_state.json"), ttl=1.0, default={})
            if first_loop or ws_manager.is_state_dirty(f"quota_{client_id}", raw_goal_state, max_idle_seconds=5.0):
                await websocket.send_json(format_ws_event(WSEventType.QUOTA_UPDATE, raw_goal_state))

            screener_targets = read_json_cached(os.path.join(BASE_DIR, "screener_targets.json"), ttl=2.0, default={
                "long": "PENDING", "short": "PENDING", "timestamp": 0
            })
            if first_loop or ws_manager.is_state_dirty(f"screener_{client_id}", screener_targets, max_idle_seconds=10.0):
                await websocket.send_json(format_ws_event(WSEventType.SCREENER_UPDATE, screener_targets))

            # 7. Microstructure / IFF overlay
            vah_val = get_vah_val(active_symbol)
            latest_obi = 0.0
            if active_symbol in signals_data and signals_data[active_symbol]:
                latest_obi = signals_data[active_symbol][-1].get("features", {}).get("order_book_imbalance", 0.0)
            microstructure_payload = {
                "symbol":      active_symbol,
                "vpoc_price":  get_vpoc(active_symbol),
                "vah":         vah_val[0] if vah_val else None,
                "val":         vah_val[1] if vah_val else None,
                "cvd_trend":   get_cvd(active_symbol),
                "cot_zscore":  get_cot_zscore(active_symbol),
                "flow_score":  get_flow_score(active_symbol, latest_obi),
                "iff_available": _IFF_AVAILABLE,
            }
            if first_loop or ws_manager.is_state_dirty(f"micro_{client_id}_{active_symbol}", microstructure_payload, max_idle_seconds=2.0):
                await websocket.send_json(format_ws_event(WSEventType.MICROSTRUCTURE, microstructure_payload))

            # 8. Engine Health & Event Bus Structured Events
            health_payload = event_bus.get_engine_health()["data"]
            if first_loop or ws_manager.is_state_dirty(f"health_{client_id}", health_payload, max_idle_seconds=5.0):
                await websocket.send_json(format_ws_event(WSEventType.ENGINE_HEALTH, health_payload))

            # 9. Market Session Status
            session_summary = get_market_sessions_summary()
            sym_open, sym_reason, sym_info = is_market_session_open(active_symbol)
            session_summary["current_symbol"] = sym_info
            if first_loop or ws_manager.is_state_dirty(f"session_{client_id}_{active_symbol}", session_summary, max_idle_seconds=10.0):
                await websocket.send_json(format_ws_event(WSEventType.MARKET_SESSION, session_summary))

            first_loop = False

    except WebSocketDisconnect:
        await ws_manager.disconnect(websocket)
        log.info("[WS-Trading] Disconnected %s", client_id)
    except Exception as e:
        log.debug("[WS-Trading] Exception for %s: %s", client_id, e)
        await ws_manager.disconnect(websocket)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)

