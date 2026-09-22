"""
services/run_backend.py — TEDENG Unified Backend

Runs the Data Pipeline AND Core Brain in two threads that share
an in-process broker queue. Signals are written to signals_store.json
so the Streamlit dashboard can read them without Redis.

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
from execution.oms import AlpacaOMS
from execution.simulated_oms import SimulatedFuturesOMS

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BACKEND] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
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
        aggregation = self.ma.aggregate(ridge_sig, xgb_sig, lstm_sig, garch_vol)
        signal      = self.ss.standardize(instr, aggregation, payload, t0)
        return signal


# ─────────────────────────────────────────────────────────────────────────────
# MAIN
# ─────────────────────────────────────────────────────────────────────────────

def main() -> None:
    log.info("══════════════════════════════════════════════")
    log.info("  TEDENG Backend starting …")
    log.info("  Instruments : %s", config.INSTRUMENTS)
    log.info("  Poll every  : %ds", config.POLL_INTERVAL_SECONDS)
    log.info("  Signals →   : signals_store.json")
    log.info("══════════════════════════════════════════════")

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
        
        for payload in batch:
            instr = payload["instrument"]
            close_price = payload.get("close", payload.get("ohlcv", {}).get("close", 0.0))
            current_prices[instr] = close_price
            
            try:
                # 1. Generate Signal
                signal = brain.process(payload)
                write_signal(signal)
                log.info(
                    "  ✓ %-10s  dir=%+.4f  conf=%.3f  regime=%-18s  latency=%.1fms",
                    instr,
                    signal["direction_magnitude"],
                    signal["confidence_score"],
                    signal["regime_flag"],
                    signal["latency_ms"],
                )
                # 2. Execution Sizing (EE) - passing instr_exp for Take-Profit logic
                proposed_order = ee.size_order(signal, instr_exp)
                if not proposed_order:
                    continue # Confidence too low, skip execution
                    
                # 3. Risk Guard (RG)
                evaluated_order = rg.check_order(proposed_order)
                
                # 4. OMS Execution
                if evaluated_order["risk_state"] == "APPROVED":
                    evaluated_order = oms.submit_order(evaluated_order, current_prices[instr])
                else:
                    log.warning("  ! %-10s  Order REJECTED by Risk Guard: %s", instr, evaluated_order.get("failed_check"))
                    
                write_execution_log(evaluated_order)
                
            except Exception as exc:
                log.error("  ✗ %s: %s", instr, exc, exc_info=True)
                
        if hasattr(oms, "update_prices"):
            oms.update_prices(current_prices)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Backend stopped.")
