"""
tests/test_models.py — Ensemble model unit tests

Validates that all three models:
  • Output a scalar ∈ [-1, +1]
  • Handle cold-start (not trained) gracefully
  • Train without raising exceptions
  • Persist and reload weights correctly
"""

import sys
import os
import tempfile
import shutil

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import numpy as np
import pandas as pd

# Temporarily override MODEL_WEIGHTS_DIR to a temp dir for tests
import config as _cfg
_ORIG_WEIGHTS_DIR = _cfg.MODEL_WEIGHTS_DIR
_TMP_DIR = tempfile.mkdtemp(prefix="tedeng_test_")
_cfg.MODEL_WEIGHTS_DIR = _TMP_DIR
_cfg.LSTM_EPOCHS = 2          # fast for tests
_cfg.TRAINING_LOOKBACK_BARS = 80


def _make_data(n: int = 200, n_features: int = 4):
    """Returns (X, close) for testing."""
    np.random.seed(42)
    X = np.random.randn(n, n_features).astype(np.float32)
    close = pd.Series(100 + np.cumsum(np.random.randn(n)))
    return X, close


# ─────────────────────────────────────────────────────────────────────────────
# RIDGE
# ─────────────────────────────────────────────────────────────────────────────

class TestRidgeModel:
    def test_cold_start_returns_zero(self):
        from brain.models.ridge_model import RidgeModel
        m = RidgeModel()
        m.is_trained = False
        result = m.predict(np.random.randn(1, 4).astype(np.float32))
        assert result == 0.0

    def test_train_and_predict_range(self):
        from brain.models.ridge_model import RidgeModel
        X, close = _make_data()
        m = RidgeModel()
        m.train(X, close)
        assert m.is_trained
        pred = m.predict(X[-1:])
        assert -1.0 <= pred <= 1.0, f"Ridge output {pred} out of [-1, +1]"

    def test_weight_persistence(self):
        from brain.models.ridge_model import RidgeModel
        X, close = _make_data()
        m1 = RidgeModel()
        m1.train(X, close)
        pred1 = m1.predict(X[-1:])

        m2 = RidgeModel()  # loads from disk
        pred2 = m2.predict(X[-1:])
        assert abs(pred1 - pred2) < 1e-6, "Loaded model should produce identical output"


# ─────────────────────────────────────────────────────────────────────────────
# XGBOOST
# ─────────────────────────────────────────────────────────────────────────────

class TestXGBModel:
    def test_cold_start_returns_zero(self):
        from brain.models.xgb_model import XGBModel
        m = XGBModel()
        m.is_trained = False
        result = m.predict(np.random.randn(1, 4).astype(np.float32))
        assert result == 0.0

    def test_train_and_predict_range(self):
        from brain.models.xgb_model import XGBModel
        X, close = _make_data()
        m = XGBModel()
        m.train(X, close)
        assert m.is_trained
        pred = m.predict(X[-1:])
        assert -1.0 <= pred <= 1.0, f"XGB output {pred} out of [-1, +1]"

    def test_feature_importances_populated(self):
        from brain.models.xgb_model import XGBModel
        X, close = _make_data()
        m = XGBModel()
        m.train(X, close)
        assert len(m.feature_importances) > 0
        assert all(v >= 0 for v in m.feature_importances.values())

    def test_weight_persistence(self):
        from brain.models.xgb_model import XGBModel
        X, close = _make_data()
        m1 = XGBModel()
        m1.train(X, close)
        pred1 = m1.predict(X[-1:])

        m2 = XGBModel()
        pred2 = m2.predict(X[-1:])
        assert abs(pred1 - pred2) < 1e-4


# ─────────────────────────────────────────────────────────────────────────────
# LSTM
# ─────────────────────────────────────────────────────────────────────────────

class TestLSTMModel:
    def test_cold_start_returns_zero(self):
        from brain.models.lstm_model import LSTMModel
        m = LSTMModel()
        m.is_trained = False
        result = m.predict(np.random.randn(50, 4).astype(np.float32))
        assert result == 0.0

    def test_insufficient_bars_returns_zero(self):
        from brain.models.lstm_model import LSTMModel
        m = LSTMModel()
        m.is_trained = True
        m.model = object()  # dummy non-None model
        # seq_len = 30, pass only 5 bars
        result = m.predict(np.random.randn(5, 4).astype(np.float32))
        assert result == 0.0

    def test_train_and_predict_range(self):
        from brain.models.lstm_model import LSTMModel
        X, close = _make_data(n=200)
        m = LSTMModel()
        m.train(X, close)
        assert m.is_trained
        pred = m.predict(X)
        assert -1.0 <= pred <= 1.0, f"LSTM output {pred} out of [-1, +1]"


# ─────────────────────────────────────────────────────────────────────────────
# META-AGGREGATOR
# ─────────────────────────────────────────────────────────────────────────────

class TestMetaAggregator:
    def test_output_range(self):
        from brain.meta_aggregator import MetaAggregator
        ma = MetaAggregator()
        result = ma.aggregate(0.5, -0.3, 0.8, garch_vol=0.015)
        assert -1.0 <= result["blended_signal"] <= 1.0

    def test_regime_high_vol(self):
        from brain.meta_aggregator import MetaAggregator
        ma = MetaAggregator()
        result = ma.aggregate(0.1, 0.2, 0.3, garch_vol=0.99)
        assert result["regime_flag"] == "high_volatility"

    def test_regime_low_vol(self):
        from brain.meta_aggregator import MetaAggregator
        ma = MetaAggregator()
        result = ma.aggregate(0.1, 0.2, 0.3, garch_vol=0.001)
        assert result["regime_flag"] == "low_volatility"

    def test_weights_sum_to_one(self):
        from brain.meta_aggregator import MetaAggregator
        ma = MetaAggregator()
        result = ma.aggregate(0.1, 0.2, 0.3, garch_vol=0.015)
        w = result["weights_used"]
        assert abs(sum(w.values()) - 1.0) < 1e-9


# ─────────────────────────────────────────────────────────────────────────────
# SIGNAL STANDARDIZER
# ─────────────────────────────────────────────────────────────────────────────

class TestSignalStandardizer:
    def test_confidence_in_range(self):
        from brain.signal_standardizer import SignalStandardizer
        import time
        ss = SignalStandardizer()
        aggregation = {
            "blended_signal": 0.65,
            "regime_flag": "trending",
            "per_model": {"ridge": 0.5, "xgb": 0.7, "lstm": 0.8},
            "weights_used": {"ridge": 0.2, "xgb": 0.45, "lstm": 0.35},
        }
        payload = {"ohlcv": {"close": 34000}}
        signal = ss.standardize("BTC-USD", aggregation, payload, time.time())

        assert 0.0 <= signal["confidence_score"] <= 1.0
        assert -1.0 <= signal["direction_magnitude"] <= 1.0
        assert signal["signal_id"].startswith("sig_")
        assert signal["instrument"] == "BTC-USD"


# ─────────────────────────────────────────────────────────────────────────────
# CLEANUP
# ─────────────────────────────────────────────────────────────────────────────

def teardown_module(module):
    shutil.rmtree(_TMP_DIR, ignore_errors=True)
    _cfg.MODEL_WEIGHTS_DIR = _ORIG_WEIGHTS_DIR
