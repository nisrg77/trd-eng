"""
services/run_brain.py — [PP→M1/M2/M3→MA→SS] Core Brain Service

Runnable microservice that:
  1. Subscribes to  tedeng:features  (from run_data_pipeline)
  2. For each feature payload:
       a. Normalises features via FeaturePreprocessor
       b. Runs Ridge / XGBoost / LSTM models (trains if needed)
       c. Blends signals via MetaAggregator (regime-based)
       d. Standardises into canonical signal packet via SignalStandardizer
  3. Publishes signal to  tedeng:signals

Usage:
    python services/run_brain.py
"""

import sys
import os
import time
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from brain.preprocessor import FeaturePreprocessor
from brain.models.ridge_model import RidgeModel
from brain.models.xgb_model import XGBModel
from brain.models.lstm_model import LSTMModel
from brain.meta_aggregator import MetaAggregator
from brain.signal_standardizer import SignalStandardizer
from middleware.broker import Broker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [BRAIN] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


class CoreBrain:
    """
    Orchestrates the full PP → M1/M2/M3 → MA → SS pipeline.
    One set of models per instrument (lazy-initialised on first message).
    """

    def __init__(self) -> None:
        self.pp = FeaturePreprocessor()
        self.ma = MetaAggregator()
        self.ss = SignalStandardizer()

        # Per-instrument model instances (populated on first message)
        self._ridge: dict[str, RidgeModel] = {}
        self._xgb:   dict[str, XGBModel]   = {}
        self._lstm:  dict[str, LSTMModel]   = {}

    def _get_models(self, instrument: str):
        if instrument not in self._ridge:
            log.info("Initialising models for %s …", instrument)
            self._ridge[instrument] = RidgeModel()
            self._xgb[instrument]   = XGBModel()
            self._lstm[instrument]  = LSTMModel()
        return (
            self._ridge[instrument],
            self._xgb[instrument],
            self._lstm[instrument],
        )

    def process(self, payload: dict) -> dict:
        """
        Full pipeline execution for one feature payload.

        Parameters
        ----------
        payload : dict  feature payload from DataPipeline

        Returns
        -------
        dict  canonical signal packet
        """
        t_start = time.time()
        instrument = payload["instrument"]

        ridge, xgb, lstm = self._get_models(instrument)

        # ── PP: normalise features ─────────────────────────────────────────
        X, x_latest, close = self.pp.transform(payload)

        # ── Walk-forward retraining (if due) ──────────────────────────────
        ridge.maybe_retrain(X, close)
        xgb.maybe_retrain(X, close)
        lstm.maybe_retrain(X, close)

        # ── Inference ─────────────────────────────────────────────────────
        ridge_sig = ridge.predict(x_latest)
        xgb_sig   = xgb.predict(x_latest)
        lstm_sig  = lstm.predict(X)

        # ── MA: regime-weighted blend ──────────────────────────────────────
        garch_vol = payload["features"].get("garch_vol", 0.01)
        aggregation = self.ma.aggregate(ridge_sig, xgb_sig, lstm_sig, garch_vol)

        # ── SS: canonical signal packet ────────────────────────────────────
        signal = self.ss.standardize(instrument, aggregation, payload, t_start)

        return signal


def main() -> None:
    log.info("Starting TEDENG Core Brain Service")
    log.info("Subscribing to : %s", config.REDIS_CHANNEL_FEATURES)
    log.info("Publishing to  : %s", config.REDIS_CHANNEL_SIGNALS)

    brain = CoreBrain()
    broker = Broker()
    signal_broker = Broker()  # separate broker instance for publishing

    log.info("Waiting for feature payloads …")
    for payload in broker.subscribe(config.REDIS_CHANNEL_FEATURES):
        instrument = payload.get("instrument", "UNKNOWN")
        log.info("Received features for %s", instrument)

        try:
            signal = brain.process(payload)
            signal_broker.publish(config.REDIS_CHANNEL_SIGNALS, signal)
            log.info(
                "  → Signal published | dir=%.4f  conf=%.3f  regime=%s  latency=%.1fms",
                signal["direction_magnitude"],
                signal["confidence_score"],
                signal["regime_flag"],
                signal["latency_ms"],
            )
        except Exception as exc:
            log.error("Brain processing error for %s: %s", instrument, exc, exc_info=True)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Core Brain Service stopped by user.")
