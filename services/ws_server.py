import asyncio
import json
import os
import random
import time
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="TEDENG ML Engine WebSocket Server")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
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
    base = current_price or 86000.0
    
    cum_bid = 0.0
    cum_ask = 0.0
    for i in range(1, 11):
        bp = base - (i * 1.5) + random.uniform(-0.2, 0.2)
        bs = random.uniform(0.05, 1.5)
        cum_bid += bs
        bids.append({"price": round(bp, 2), "size": round(bs, 4), "total": round(cum_bid, 4)})

        ap = base + (i * 1.5) + random.uniform(-0.2, 0.2)
        as_size = random.uniform(0.05, 1.5)
        cum_ask += as_size
        asks.append({"price": round(ap, 2), "size": round(as_size, 4), "total": round(cum_ask, 4)})

    return {
        "bids": bids,
        "asks": asks,
        "spread": round(asks[0]["price"] - bids[0]["price"], 2)
    }

@app.websocket("/ws/trading")
async def websocket_endpoint(websocket: WebSocket, symbol: str = "BTC-USD"):
    await websocket.accept()
    print(f"[WS] Client connected for symbol: {symbol}")
    
    last_signal_count = 0
    last_exec_count = 0
    current_price = 86150.0

    try:
        while True:
            # 1. Read simulated account state
            account = read_json_safe(ACCOUNT_FILE, default={
                "equity": 1000.0,
                "realized_pl": 0.0,
                "positions": {}
            })
            
            # Extract current price for symbol if in positions
            if symbol in account.get("positions", {}):
                pos = account["positions"][symbol]
                if pos.get("current_price"):
                    current_price = pos["current_price"]

            await websocket.send_json({
                "type": "ACCOUNT_UPDATE",
                "payload": account
            })

            # 2. Emit tick data
            now_ts = int(time.time())
            # Floor to 5-second bar bucket
            bar_time = (now_ts // 5) * 5
            price_variation = random.uniform(-5.0, 5.0)
            current_price = max(10.0, current_price + price_variation)
            
            tick_payload = {
                "time": bar_time,
                "open": round(current_price - random.uniform(-2, 2), 2),
                "high": round(current_price + random.uniform(0.5, 4), 2),
                "low": round(current_price - random.uniform(0.5, 4), 2),
                "close": round(current_price, 2),
                "volume": round(random.uniform(0.5, 12.0), 4)
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

            # 6. Read Quota State and Screener Targets
            quota_state = read_json_safe(os.path.join(BASE_DIR, "quota_state.json"), default={
                "crypto": {"completed": 0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0},
                "futures": {"completed": 0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0}
            })
            await websocket.send_json({"type": "QUOTA_UPDATE", "payload": quota_state})

            screener_targets = read_json_safe(os.path.join(BASE_DIR, "screener_targets.json"), default={
                "long": "PENDING", "short": "PENDING", "timestamp": 0
            })
            await websocket.send_json({"type": "SCREENER_UPDATE", "payload": screener_targets})

            await asyncio.sleep(0.5) # 500ms broadcast loop
            
    except WebSocketDisconnect:
        print("[WS] Client disconnected")
    except Exception as e:
        print(f"[WS] Error: {e}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
