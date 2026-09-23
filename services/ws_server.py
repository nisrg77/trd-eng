import asyncio
import json
import os
import random
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
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

app = FastAPI(title="TEDENG ML Engine WebSocket Server")

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

def read_json_safe(filepath, default=None):
    if not os.path.exists(filepath):
        return default
    try:
        with open(filepath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default

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

def fetch_symbol_last_price(symbol: str) -> float:
    if symbol in DEFAULT_PRICES:
        return DEFAULT_PRICES[symbol]
    signals = read_json_safe(SIGNALS_FILE, default={})
    if symbol in signals and signals[symbol]:
        c = signals[symbol][-1].get("ohlcv", {}).get("close")
        if c:
            return float(c)
    return 150.0

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

@app.websocket("/ws/trading")
async def websocket_endpoint(websocket: WebSocket, symbol: str = "BTC-USD"):
    await websocket.accept()
    print(f"[WS] Client connected for symbol: {symbol}")
    
    last_signal_count = 0
    last_exec_count = 0
    
    # Initialize price correctly for the selected symbol (handles custom searched tickers as well)
    signals_init = read_json_safe(SIGNALS_FILE, default={})
    current_price = fetch_symbol_last_price(symbol)
    if symbol in signals_init and len(signals_init[symbol]) > 0:
        c = signals_init[symbol][-1].get("ohlcv", {}).get("close")
        if c:
            current_price = float(c)

    try:
        # Send initial 50 historical candles for immediate TradingView chart rendering
        history = []
        now_sec = (int(time.time()) // 5) * 5
        p = current_price
        for i in range(50, 0, -1):
            t = now_sec - (i * 5)
            var = max(0.02, p * 0.0003)
            o = round(p + random.uniform(-var, var), 2)
            h = round(max(o, p) + random.uniform(0.01, var), 2)
            l = round(min(o, p) - random.uniform(0.01, var), 2)
            c = round(p, 2)
            v = round(random.uniform(5.0, 100.0), 2)
            history.append({"time": t, "open": o, "high": h, "low": l, "close": c, "volume": v})
            p = c

        await websocket.send_json({"type": "HISTORICAL_CANDLES", "payload": history})

        while True:

            # 1. Read simulated account state
            account = read_json_safe(ACCOUNT_FILE, default={
                "equity": 1000.0,
                "realized_pl": 0.0,
                "positions": {}
            })
            
            # Read latest signals
            signals_data = read_json_safe(SIGNALS_FILE, default={})
            
            # Extract current price for symbol if in positions or latest signal
            if symbol in account.get("positions", {}):
                pos = account["positions"][symbol]
                if pos.get("current_price"):
                    current_price = pos["current_price"]
            elif symbol in signals_data and len(signals_data[symbol]) > 0:
                c = signals_data[symbol][-1].get("ohlcv", {}).get("close")
                if c:
                    current_price = float(c)

            await websocket.send_json({
                "type": "ACCOUNT_UPDATE",
                "payload": account
            })

            # 2. Emit tick data scaled to instrument price
            now_ts = int(time.time())
            # Floor to 5-second bar bucket
            bar_time = (now_ts // 5) * 5
            max_var = max(0.02, current_price * 0.0003)
            price_variation = random.uniform(-max_var, max_var)
            current_price = max(1.0, current_price + price_variation)
            
            tick_payload = {
                "time": bar_time,
                "open": round(current_price - random.uniform(-max_var * 0.5, max_var * 0.5), 2),
                "high": round(current_price + random.uniform(max_var * 0.2, max_var), 2),
                "low": round(current_price - random.uniform(max_var * 0.2, max_var), 2),
                "close": round(current_price, 2),
                "volume": round(random.uniform(1.0, 50.0), 2)
            }
            await websocket.send_json({"type": "TICK", "payload": tick_payload})

            # 3. Emit live Order Book update
            order_book = generate_mock_order_book(current_price)
            await websocket.send_json({"type": "ORDER_BOOK", "payload": order_book})

            # 4. Read ML Signals
            signals_data = read_json_safe(SIGNALS_FILE, default={})
            symbol_signals = signals_data.get(symbol, [])
            if len(symbol_signals) > last_signal_count:
                new_signals = symbol_signals[last_signal_count:]
                for sig in new_signals:
                    await websocket.send_json({"type": "ML_SIGNAL", "payload": sig})
                last_signal_count = len(symbol_signals)

            # 5. Read Executions
            exec_list = read_json_safe(EXECUTIONS_FILE, default=[])
            if isinstance(exec_list, list) and len(exec_list) > last_exec_count:
                new_execs = exec_list[last_exec_count:]
                for ex in new_execs:
                    await websocket.send_json({"type": "EXECUTION", "payload": ex})
                last_exec_count = len(exec_list)

            # 6. Read Goal / Quota State and Screener Targets
            from goals.goal_module import monthly_progress_summary, load_state
            goal_summary = monthly_progress_summary()
            raw_goal_state = read_json_safe(os.path.join(BASE_DIR, "quota_state.json"), default={})
            await websocket.send_json({"type": "QUOTA_UPDATE", "payload": raw_goal_state})
            await websocket.send_json({"type": "GOAL_UPDATE", "payload": goal_summary})

            screener_targets = read_json_safe(os.path.join(BASE_DIR, "screener_targets.json"), default={
                "long": "PENDING", "short": "PENDING", "timestamp": 0
            })
            await websocket.send_json({"type": "SCREENER_UPDATE", "payload": screener_targets})

            # 7. Microstructure / IFF overlay
            vah_val = get_vah_val(symbol)
            latest_obi = 0.0
            if symbol in signals_data and signals_data[symbol]:
                latest_obi = signals_data[symbol][-1].get("features", {}).get("order_book_imbalance", 0.0)
            microstructure_payload = {
                "symbol":      symbol,
                "vpoc_price":  get_vpoc(symbol),
                "vah":         vah_val[0] if vah_val else None,
                "val":         vah_val[1] if vah_val else None,
                "cvd_trend":   get_cvd(symbol),
                "cot_zscore":  get_cot_zscore(symbol),   # 0.0 until Phase 5
                "flow_score":  get_flow_score(symbol, latest_obi),
                "iff_available": _IFF_AVAILABLE,
            }
            await websocket.send_json({"type": "MICROSTRUCTURE", "payload": microstructure_payload})

            # 8. Engine Health & Event Bus Structured Events
            from middleware.event_bus import event_bus
            await websocket.send_json(event_bus.get_engine_health())

            # 9. Market Session Status
            from execution.market_session import is_market_session_open, get_market_sessions_summary
            session_summary = get_market_sessions_summary()
            sym_open, sym_reason, sym_info = is_market_session_open(symbol)
            session_summary["current_symbol"] = sym_info
            await websocket.send_json({"type": "MARKET_SESSION", "payload": session_summary})

            await asyncio.sleep(0.5) # 500ms broadcast loop
            
    except WebSocketDisconnect:
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
