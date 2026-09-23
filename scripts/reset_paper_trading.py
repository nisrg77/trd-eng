"""
scratch/reset_paper_trading.py — Full clean reset to paper trading state
Wipes all test entries, positions, P&L, quota counters.
"""
import json
import os

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

files = {
    "simulated_account.json": {
        "equity": 1000.0,
        "balance": 1000.0,
        "realized_pl": 0.0,
        "positions": {},
        "unrealized_pl": 0.0,
        "total_pl": 0.0,
        "trade_log": [],
        "note": "Clean paper trading start"
    },
    "quota_state.json": {
        "crypto": {"trades_today": 0, "realized_pnl_this_month_usd": 0.0, "completed": 0,
                   "last_reset_day": "", "last_reset_month": ""},
        "stock":  {"trades_today": 0, "realized_pnl_this_month_usd": 0.0, "completed": 0,
                   "last_reset_day": "", "last_reset_month": ""},
        "futures": {"trades_today": 0, "realized_pnl_this_month_usd": 0.0, "completed": 0,
                    "last_reset_day": "", "last_reset_month": ""},
        "engine_paused": False
    },
    "signals_store.json": {},
    "execution_store.json": [],
    "screener_cache.json": {},
    "screener_targets.json": {},
}

for fname, content in files.items():
    path = os.path.join(BASE, fname)
    with open(path, "w") as f:
        json.dump(content, f, indent=2)
    print(f"[RESET] {fname}")

# Clear decision_trace.jsonl
dt_path = os.path.join(BASE, "decision_trace.jsonl")
with open(dt_path, "w") as f:
    pass
print(f"[RESET] decision_trace.jsonl")

# ── RESET MONGODB (IF CONFIGURED) ──
import sys
sys.path.insert(0, BASE)
import config

uri = getattr(config, "MONGODB_URI", "").strip()
if uri and "<db_password>" not in uri:
    try:
        import pymongo
        client = pymongo.MongoClient(uri, serverSelectionTimeoutMS=5000)
        db_name = "trade-db"
        if "/" in uri.split("?")[0]:
            possible_name = uri.split("?")[0].split("/")[-1]
            if possible_name:
                db_name = possible_name
        
        db = client[db_name]
        
        # Reset account state
        db["account"].update_one(
            {"id": "primary_account"},
            {"$set": files["simulated_account.json"]},
            upsert=True
        )
        print(f"[RESET MONGODB] account reset to $1000")
        
        # Reset quota state
        db["quota"].update_one(
            {"id": "quota_summary"},
            {"$set": {"id": "quota_summary", **files["quota_state.json"]}},
            upsert=True
        )
        print(f"[RESET MONGODB] quota limits reset")
        
        # Clear positions, trades, and rejections
        db["positions"].delete_many({})
        db["trades"].delete_many({})
        db["gate_rejections"].delete_many({})
        print(f"[RESET MONGODB] cleared positions, trades, gate_rejections")
        
        print("\n=== All LOCAL and MONGODB state files reset. Paper trading starts fresh with $1000 equity. ===")
    except Exception as e:
        print(f"\n[WARNING] Could not reset MongoDB: {e}")
else:
    print("\n=== All LOCAL state files reset. Paper trading starts fresh with $1000 equity. (MongoDB not configured) ===")

