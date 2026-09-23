"""
start_engine.py — TRDENG Master Deployment Initializer

Use this script to deploy the engine in full-autonomous mode.
- Sets initial capital based on config.py / .env
- Wipes old test history (execution_store, signals_store, quota_state)
- Boots all processes headless via PM2
"""

import os
import json
import logging
import subprocess

import config

logging.basicConfig(level=logging.INFO, format="%(asctime)s [DEPLOY] %(message)s")
log = logging.getLogger(__name__)

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

def clear_file(filename: str, default_content):
    path = os.path.join(BASE_DIR, filename)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(default_content, f, indent=2)
    log.info(f"Reset {filename}")

def deploy():
    log.info("="*60)
    log.info("TRDENG MASTER DEPLOYMENT INITIALIZER")
    log.info("="*60)
    
    # 1. Initialize Simulated Account
    initial_cap = config.INITIAL_CAPITAL
    leverage = config.FUTURES_LEVERAGE
    account_state = {
        "equity": initial_cap,
        "balance": initial_cap,
        "realized_pl": 0.0,
        "active_drawdown_pct": 0.0,
        "positions": {}
    }
    clear_file("simulated_account.json", account_state)
    log.info(f"Simulated Account Initialized: ${initial_cap:.2f} Capital (Max Leverage: {leverage}x)")
    
    # 2. Reset Quota & Goal State
    from goals.goal_module import GoalModule
    clear_file("quota_state.json", GoalModule.INITIAL_STATE.copy())
    
    # 3. Reset Stores
    clear_file("execution_store.json", [])
    clear_file("signals_store.json", {})
    clear_file("screener_targets.json", {"long": "PENDING", "short": "PENDING", "timestamp": 0})
    
    # 4. Trigger PM2
    log.info("Starting PM2 Ecosystem...")
    try:
        # Assuming pm2 is installed globally via npm
        subprocess.run(["pm2", "start", "ecosystem.config.js"], check=True, cwd=BASE_DIR)
        log.info("✅ PM2 Services Started Successfully.")
    except Exception as e:
        log.error(f"Failed to start PM2: {e}")
        log.warning("Please ensure PM2 is installed: `npm install -g pm2`")
        
    log.info("Deployment Complete. TRDENG is now running autonomously.")
    log.info("Results will automatically export to baseline_results.csv when quota is met.")
    log.info("="*60)

if __name__ == "__main__":
    deploy()
