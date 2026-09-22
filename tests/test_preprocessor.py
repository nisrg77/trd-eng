"""
tests/test_preprocessor.py — PP layer unit tests

Validates:
  • Z-score mean ≈ 0, std ≈ 1 after normalisation
  • Imputation removes NaN
  • LSTM sequence reshape is correct shape
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import numpy as np
import pandas as pd

from brain.preprocessor import FeaturePreprocessor, _rolling_zscore, _impute, FEATURE_KEYS


def _make_payload(n: int = 300) -> dict:
    np.random.seed(7)
    close = 100 + np.cumsum(np.random.randn(n))
    return {
        "instrument": "TEST",
        "features": {k: 0.0 for k in FEATURE_KEYS},
        "ohlcv": {"open": 100, "high": 105, "low": 95, "close": 100, "volume": 1000},
        "_close_history": close.tolist(),
        "_feature_history": {
            "frac_diff": (np.diff(close, prepend=close[0]) * 0.5).tolist(),
            "garch_vol":  np.abs(np.random.randn(n) * 0.01).tolist(),
            "obi":        np.random.uniform(-1, 1, n).tolist(),
            "rsi_14":     np.random.uniform(20, 80, n).tolist(),
        },
    }


class TestRollingZScore:
    def test_output_approx_zero_mean(self):
        s = pd.Series(np.random.randn(200) * 10 + 50)
        z = _rolling_zscore(s, window=30)
        # After warm-up, mean should be near 0
        assert abs(z.iloc[50:].mean()) < 0.5

    def test_clipped_range(self):
        s = pd.Series([1e9] * 5 + list(np.random.randn(100)))
        z = _rolling_zscore(s, window=20)
        assert z.between(-5, 5).all(), "Z-score must be clipped to [-5, +5]"

    def test_no_nan_output(self):
        s = pd.Series(np.random.randn(100))
        z = _rolling_zscore(s)
        assert not z.isna().any(), "No NaN expected after z-score (fillna applied)"


class TestImpute:
    def test_ffill_removes_nan(self):
        s = pd.Series([1.0, np.nan, np.nan, 4.0, np.nan])
        out = _impute(s, strategy="ffill")
        assert not out.isna().any()

    def test_mean_removes_nan(self):
        s = pd.Series([1.0, np.nan, 3.0, np.nan, 5.0])
        out = _impute(s, strategy="mean")
        assert not out.isna().any()


class TestFeaturePreprocessor:
    def test_X_shape(self):
        pp = FeaturePreprocessor()
        payload = _make_payload(300)
        X, x_latest, close = pp.transform(payload)
        assert X.ndim == 2
        assert X.shape[1] == len(FEATURE_KEYS)

    def test_x_latest_shape(self):
        pp = FeaturePreprocessor()
        payload = _make_payload(300)
        X, x_latest, close = pp.transform(payload)
        assert x_latest.shape == (1, len(FEATURE_KEYS))

    def test_x_latest_is_last_row(self):
        pp = FeaturePreprocessor()
        payload = _make_payload(300)
        X, x_latest, close = pp.transform(payload)
        np.testing.assert_array_almost_equal(x_latest[0], X[-1])

    def test_close_alignment(self):
        pp = FeaturePreprocessor()
        payload = _make_payload(300)
        X, x_latest, close = pp.transform(payload)
        assert len(close) == len(X), "Close and X must have same length"

    def test_sequence_shape(self):
        pp = FeaturePreprocessor()
        payload = _make_payload(300)
        X, _, _ = pp.transform(payload)
        seq_len = 30
        seqs = pp.transform_sequence(X, seq_len=seq_len)
        n_expected = len(X) - seq_len + 1
        assert seqs.shape == (n_expected, seq_len, len(FEATURE_KEYS))

    def test_sequence_too_short_raises(self):
        pp = FeaturePreprocessor()
        X = np.random.randn(10, 4).astype(np.float32)
        with pytest.raises(ValueError):
            pp.transform_sequence(X, seq_len=30)
