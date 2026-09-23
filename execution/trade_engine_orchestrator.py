"""
execution/trade_engine_orchestrator.py — Main Trade Engine Orchestrator

Wires together:
1. Data Ingestion (Redis 'tedeng:features')
2. Feature Extraction & Regime Detection (HMM)
3. Microstructure Gating (OBI rho)
4. Screener Ranking (RVOL & Momentum)
5. Execution (OMS)

Enforces quotas via QuotaManager.
"""

import os
import sys
import json
import time
import logging
import threading
from datetime import datetime
try:
    from zoneinfo import ZoneInfo
except ImportError:
    from backports.zoneinfo import ZoneInfo

import redis

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config
from brain.hmm_regime import GaussianHMMRegimeDetector
from execution.simulated_oms import SimulatedFuturesOMS
from execution.quota_manager import quota_manager
from data_pipeline.stock_screener import stock_screener
from middleware.telemetry_db import telemetry
from middleware.webhooks import WebhookAlerts

log = logging.getLogger(__name__)

class TradeEngineOrchestrator:
    def __init__(self):
        self.redis_client = redis.Redis(host=config.REDIS_HOST, port=config.REDIS_PORT, db=config.REDIS_DB)
        self.pubsub = self.redis_client.pubsub()
        self.pubsub.subscribe(config.REDIS_CHANNEL_FEATURES)
        
        self.hmm = GaussianHMMRegimeDetector()
        self.oms = SimulatedFuturesOMS()
        
        # Cache for screener targets
        self.target_long = None
        self.target_short = None
        self.last_screener_update = 0
        
        # Background thread for screener updates (every 15 mins)
        self.screener_thread = threading.Thread(target=self._update_screener_targets_loop, daemon=True)
        self.screener_thread.start()

    def _is_rth(self) -> bool:
        """Returns True if current time is within US Equity Regular Trading Hours (9:30 - 16:00 EST)."""
        now_est = datetime.now(ZoneInfo("America/New_York"))
        # Check if it's a weekday (0 = Monday, 4 = Friday)
        if now_est.weekday() > 4:
            return False
            
        current_time = now_est.time()
        # 9:30 AM
        start_time = datetime.strptime("09:30", "%H:%M").time()
        # 4:00 PM
        end_time = datetime.strptime("16:00", "%H:%M").time()
        
        return start_time <= current_time <= end_time

    def _update_screener_targets_loop(self):
        """Periodically update the screener targets to avoid blocking the main event loop."""
        while True:
            # Only update screener if it's RTH or shortly before
            now_est = datetime.now(ZoneInfo("America/New_York"))
            if now_est.weekday() <= 4 and 8 <= now_est.hour <= 16:
                try:
                    log.info("[Orchestrator] Updating US Stock Futures Screener Targets...")
                    top_long, bottom_short = stock_screener.get_targets()
                    if top_long and bottom_short:
                        self.target_long = top_long
                        self.target_short = bottom_short
                        self.last_screener_update = time.time()
                        log.info(f"[Orchestrator] Targets Updated -> Long: {self.target_long}, Short: {self.target_short}")
                        
                        # Write to file for WebSocket UI consumption
                        targets_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "screener_targets.json")
                        with open(targets_file, "w") as f:
                            json.dump({"long": top_long, "short": bottom_short, "timestamp": self.last_screener_update}, f)
                            
                except Exception as e:
                    log.error(f"[Orchestrator] Screener update failed: {e}")
            
            time.sleep(15 * 60) # 15 minutes

    def process_feature_payload(self, payload: dict):
        instrument = payload.get("instrument")
        features = payload.get("features", {})
        ohlcv = payload.get("ohlcv", {})
        
        if not instrument or not features or not ohlcv:
            return

        current_price = ohlcv.get("close", 0.0)
        garch_vol = features.get("garch_vol", 0.0)
        rsi_14 = features.get("rsi_14", 50.0)
        obi_rho = features.get("order_book_imbalance", 0.0)
        
        # Estimate ATR proxy for OMS if not provided (assume 1.5% of price or garch scaled)
        atr_proxy = current_price * garch_vol if garch_vol > 0 else current_price * 0.015

        is_crypto = instrument in config.CRYPTO_INSTRUMENTS
        asset_class = "crypto" if is_crypto else "futures"
        
        # Enforce Market Session constraint for US Futures & Equities
        from execution.market_session import is_market_session_open
        is_open, session_msg, _ = is_market_session_open(instrument)
        if not is_open:
            # Still update OMS prices so trailing stops can be managed if positions are held
            self.oms.update_prices({instrument: current_price}, {instrument: atr_proxy})
            return # Skip entry logic outside active session
            
        # 1. Update OMS Prices & Handle Scaled Exits / Trailing Stops
        exits = self.oms.update_prices({instrument: current_price}, {instrument: atr_proxy})
        if exits:
            for ex in exits:
                quota_manager.log_closed_trade(asset_class, ex.get("realized_pnl", 0.0))
        
        # Absolute Ruin Check: Stop if monthly capital is exhausted
        account_state = self.oms.get_account_state()
        if account_state["equity"] < 5.0:
            log.warning(f"[Orchestrator] CRITICAL: Monthly capital is exhausted (Equity: ${account_state['equity']:.2f}). Halting new entries.")
            return
        
        if not quota_manager.can_trade(asset_class):
            return # Quota reached, skip entry logic

        # 2. Regime Detection
        regime_info = self.hmm.predict_regime(garch_vol, rsi_14, obi_rho, is_crypto=is_crypto)
        regime_state = regime_info["regime_flag"]
        
        # Telemetry Log
        telemetry.log_hmm_state(instrument, regime_state, regime_info["probabilities"].get(regime_state, 0.0))
        
        # Determine Bull/Bear from "trending" + RSI direction
        is_bull = regime_state == "trending" and rsi_14 > 50
        is_bear = regime_state == "trending" and rsi_14 < 50
        
        action = None
        detail = ""

        # 3. Entry Logic & Microstructure Gating
        if is_crypto:
            if is_bull and obi_rho > 0.3:
                action = "BUY"
                detail = "Crypto Bull + OBI > 0.3"
            elif is_bear and obi_rho < -0.3:
                action = "SELL"
                detail = "Crypto Bear + OBI < -0.3"
        else:
            if self.target_long and self.target_short:
                if instrument == self.target_long and is_bull and obi_rho > 0.3:
                    action = "BUY"
                    detail = f"US Futures Long Target ({instrument}) + Bull + OBI > 0.3"
                elif instrument == self.target_short and is_bear and obi_rho < -0.3:
                    action = "SELL"
                    detail = f"US Futures Short Target ({instrument}) + Bear + OBI < -0.3"

        if action:
            order = {
                "instrument": instrument,
                "action": action,
                "portfolio_allocation_pct": 0.10,
                "atr": atr_proxy,
                "risk_state": "APPROVED"
            }
            
            log.info(f"[Orchestrator] Attempting {action} on {instrument}: {detail}")
            result = self.oms.submit_order(order, current_price, obi_rho)
            
            if result.get("oms_state") == "SUBMITTED":
                qty = result.get("qty", 1.0)
                telemetry.log_execution(instrument, action, qty, current_price, slippage=0.01, latency_ms=15.0, hmm_state=regime_state)
                WebhookAlerts.alert_trade_fill(instrument, action, qty, current_price)
                
                # Note: We now properly track actual closed trades via update_prices exits above. 

    def run(self):
        log.info("[Orchestrator] Trade Engine Orchestrator Started.")
        log.info("Listening for 'tedeng:features' on Redis...")
        
        for message in self.pubsub.listen():
            if message["type"] == "message":
                try:
                    payload = json.loads(message["data"].decode("utf-8"))
                    self.process_feature_payload(payload)
                except Exception as e:
                    log.error(f"[Orchestrator] Error processing message: {e}")

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [ORCHESTRATOR] %(message)s")
    orchestrator = TradeEngineOrchestrator()
    orchestrator.run()
