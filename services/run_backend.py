"""
services/run_backend.py — TEDENG Unified Backend

Runs the Data Pipeline AND Core Brain in two threads that share
an in-process broker queue. Signals are written to signals_store.json
so the frontend dashboard can read them without Redis.

Usage:
    python services/run_backend.py
"""

from __future__ import annotations

import sys
import os
import time
import json
import logging
import threading
import pandas as pd


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from data_pipeline.pipeline import DataPipeline
from brain.preprocessor import FeaturePreprocessor
from brain.models.ridge_model import RidgeModel
from brain.models.xgb_model import XGBModel
from brain.models.lstm_model import LSTMModel
from brain.meta_aggregator import MetaAggregator
from brain.signal_standardizer import SignalStandardizer
from middleware.file_store import write_signal, write_execution_log
from execution.engine import ExecutionEngine
from execution.risk import RiskGuard
from execution.simulated_oms import SimulatedFuturesOMS
from data_pipeline.stock_screener import stock_screener

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BACKEND] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
import utils.time_utils as time_utils
logging.Formatter.converter = lambda *args: time_utils.now_ist().timetuple()
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# CORE BRAIN  (inline — same process as DP so we avoid inter-process IPC)
# ─────────────────────────────────────────────────────────────────────────────

class CoreBrain:
    def __init__(self) -> None:
        self.pp = FeaturePreprocessor()
        self.ma = MetaAggregator()
        self.ss = SignalStandardizer()
        self._ridge: dict = {}
        self._xgb:   dict = {}
        self._lstm:  dict = {}

    def _models(self, instrument: str):
        if instrument not in self._ridge:
            log.info("Initialising models for %s …", instrument)
            self._ridge[instrument] = RidgeModel()
            self._xgb[instrument]   = XGBModel()
            self._lstm[instrument]  = LSTMModel()
        return self._ridge[instrument], self._xgb[instrument], self._lstm[instrument]

    def process(self, payload: dict) -> dict:
        t0 = time.time()
        instr = payload["instrument"]
        ridge, xgb, lstm = self._models(instr)

        X, x_latest, close = self.pp.transform(payload)
        ridge.maybe_retrain(X, close)
        xgb.maybe_retrain(X, close)
        lstm.maybe_retrain(X, close)

        ridge_sig = ridge.predict(x_latest)
        xgb_sig   = xgb.predict(x_latest)
        lstm_sig  = lstm.predict(X)

        garch_vol   = payload["features"].get("garch_vol", 0.01)
        obi_rho     = payload["features"].get("order_book_imbalance", 0.0)
        aggregation = self.ma.aggregate(ridge_sig, xgb_sig, lstm_sig, garch_vol)

        # ── IFF Gate: institutional flow veto & scale applied right after MA ──
        try:
            from alpha_overlay.iff import apply_iff_gate
            gated_signal, flow_score, iff_veto = apply_iff_gate(
                aggregation["blended_signal"], instr, obi_rho
            )
            aggregation["blended_signal"] = gated_signal
            aggregation["flow_score"] = flow_score
            aggregation["iff_veto"] = iff_veto
        except Exception as e:
            log.warning("IFF gate unavailable in backend: %s", e)

        signal = self.ss.standardize(instr, aggregation, payload, t0)
        return signal


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def _start_screener_background():
    targets_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screener_targets.json")
    try:
        top_long, bottom_short = stock_screener.get_targets()
        with open(targets_file, "w") as f:
            json.dump({"long": top_long, "short": bottom_short, "timestamp": time.time()}, f, indent=2)
    except Exception:
        pass

    def _screener_worker():
        while True:
            try:
                top_long, bottom_short = stock_screener.get_targets()
                if top_long and bottom_short:
                    with open(targets_file, "w") as f:
                        json.dump({"long": top_long, "short": bottom_short, "timestamp": time.time()}, f, indent=2)
                    log.info("[BACKEND] 7-day Screener targets verified -> Long: %s, Short: %s", top_long, bottom_short)
            except Exception as e:
                log.error("[BACKEND] Screener worker error: %s", e)
            time.sleep(30 * 60)

    t = threading.Thread(target=_screener_worker, daemon=True)
    t.start()


def main() -> None:
    # 1. 7-Day Screener Caching & Target Rotation
    top_candidates = stock_screener.get_top_candidates(count=15)
    active_stocks = stock_screener.select_active_targets(n=2, count=15)
    
    # Configure live instruments (Crypto + sampled active stocks)
    config.STOCK_INSTRUMENTS = list(dict.fromkeys(active_stocks + ["AAPL", "SPY"]))
    config.INSTRUMENTS = config.CRYPTO_INSTRUMENTS + config.STOCK_INSTRUMENTS

    log.info("══════════════════════════════════════════════")
    log.info("  TEDENG Backend starting …")
    log.info("  Instruments : %s", config.INSTRUMENTS)
    log.info("  7-Day SSF Pool : %d stocks cached (Active: %s)", len(top_candidates), active_stocks)
    log.info("  Poll every  : %ds", config.POLL_INTERVAL_SECONDS)
    log.info("  Signals →   : signals_store.json")
    log.info("══════════════════════════════════════════════")

    _start_screener_background()

    dp    = DataPipeline()
    brain = CoreBrain()
    ee    = ExecutionEngine()
    rg    = RiskGuard()
    if config.USE_SIMULATED_FUTURES:
        oms = SimulatedFuturesOMS()
        log.info("Using SimulatedFuturesOMS (10x Leverage) for Execution.")
    else:
        oms = AlpacaOMS()
        log.info("Using AlpacaOMS for Execution.")

    cycle = 0
    for batch in dp.stream():
        cycle += 1
        log.info("── Cycle %d ─────────────────────────────────────", cycle)
        
        # Update Risk Guard with latest portfolio exposures from OMS
        current_exp, instr_exp = oms.get_portfolio_exposures()
        rg.update_state(current_exp, instr_exp)
        
        current_prices = {}
        atr_values = {}
        
        for payload in batch:
            instr = payload["instrument"]
            close_price = payload.get("close", payload.get("ohlcv", {}).get("close", 0.0))
            current_prices[instr] = close_price
            
            features = payload.get("features", {})
            garch_vol = features.get("garch_vol", 0.015)
            atr_proxy = close_price * garch_vol if garch_vol > 0 else close_price * 0.015
            atr_values[instr] = atr_proxy
            obi_rho = features.get("order_book_imbalance", 0.0)

            is_crypto = instr in config.CRYPTO_INSTRUMENTS
            asset_class = "crypto" if is_crypto else "futures"
            
            try:
                # 1. Generate Signal
                signal = brain.process(payload)
                
                # Compute Dead-Day Filter and Composite Conviction using real historical OHLCV DataFrame
                from data_pipeline.dead_day_filter import compute_dead_day_and_conviction
                df_hist = payload.get("_df")
                if df_hist is None or len(df_hist) < 5:
                    close_hist = payload.get("_close_history", [close_price] * 20)
                    df_hist = pd.DataFrame({
                        "Close": close_hist,
                        "High": close_hist,
                        "Low": close_hist,
                        "Volume": [payload.get("ohlcv", {}).get("volume", 1000.0)] * len(close_hist)
                    })

                dead_day_res = compute_dead_day_and_conviction(
                    df_hist,
                    signal.get("confidence_score", 0.5),
                    signal.get("flow_score", 0.0),
                    signal.get("direction_magnitude", 0.0),
                    is_crypto,
                    symbol=instr
                )


                signal["dead_day_result"] = dead_day_res
                signal["conviction_score"] = dead_day_res["effective_conviction"]
                
                write_signal(signal)
                log.info(
                    "  ✓ %-10s  dir=%+.4f  conf=%.3f  conv=%.3f  regime=%-18s  latency=%.1fms",
                    instr,
                    signal["direction_magnitude"],
                    signal["confidence_score"],
                    dead_day_res["effective_conviction"],
                    signal["regime_flag"],
                    signal["latency_ms"],
                )
                # Check Market Session before attempting new entry orders
                from execution.market_session import is_market_session_open
                is_open, session_reason, _ = is_market_session_open(instr)
                if not is_open and instr not in instr_exp:
                    # US Market is closed: do not force new entry orders
                    continue

                # 2. Execution Sizing (EE) - passing instr_exp for Take-Profit logic
                proposed_order = ee.size_order(signal, instr_exp)
                if not proposed_order:
                    continue # Confidence too low, dead day, ceiling hit, or no trade
                    
                proposed_order["atr"] = atr_proxy

                # 3. Risk Guard (RG)
                evaluated_order = rg.check_order(proposed_order)
                
                # 4. OMS Execution
                if evaluated_order["risk_state"] == "APPROVED":
                    evaluated_order = oms.submit_order(evaluated_order, current_prices[instr], obi_rho=obi_rho)
                    write_execution_log(evaluated_order)
                else:
                    evaluated_order["timestamp_executed"] = time.time()
                    evaluated_order["oms_state"] = "SKIPPED_BY_RISK"
                    log.warning("  ! %-10s  Order REJECTED by Risk Guard: %s", instr, evaluated_order.get("failed_check"))
                    # Store rejected trade in MongoDB only (not on dashboard UI)
                    try:
                        from middleware.db_manager import mongo_db
                        if mongo_db.is_connected():
                            mongo_db.save_gate_rejection({
                                "instrument": instr,
                                "asset_class": asset_class,
                                "gate": evaluated_order.get("failed_check", "RISK_GUARD"),
                                "reason": evaluated_order.get("failed_check", ""),
                                "final_action": "REJECTED",
                                "signal_direction": signal.get("direction_magnitude", 0.0),
                                "effective_conviction": signal.get("conviction_score", 0.0),
                            })
                    except Exception:
                        pass
                
            except Exception as exc:
                log.error("  ✗ %s: %s", instr, exc, exc_info=True)
                
        if hasattr(oms, "update_prices"):
            exits = oms.update_prices(current_prices, atr_values)
            if exits:
                from goals.goal_module import record_trade_result
                for ex in exits:
                    ex_instr = ex.get("instrument", "")
                    ac = "crypto" if ex_instr in config.CRYPTO_INSTRUMENTS else "stock"
                    record_trade_result(ac, ex.get("realized_pnl", 0.0))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Backend stopped.")
