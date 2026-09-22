"""
tests/test_pipeline.py — DP layer unit tests

Mocks Alpaca + Binance HTTP calls so no real network access is needed.
"""

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

import pytest
import numpy as np
import pandas as pd
from unittest.mock import patch, MagicMock

from data_pipeline.pipeline import (
    frac_diff, compute_rsi, compute_garch_vol, compute_obi, _build_payload
)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE FUNCTION UNIT TESTS
# ─────────────────────────────────────────────────────────────────────────────

class TestFracDiff:
    def test_output_length(self):
        s = pd.Series(range(1, 101), dtype=float)
        assert len(frac_diff(s, d=0.4)) == len(s)

    def test_leading_nan(self):
        s = pd.Series(range(1, 51), dtype=float)
        assert frac_diff(s, d=0.4).isna().any()

    def test_non_nan_finite(self):
        s = pd.Series(range(1, 201), dtype=float)
        result = frac_diff(s, d=0.4).dropna()
        assert np.all(np.isfinite(result))


class TestRSI:
    def test_range(self):
        close = pd.Series([100 + i * 0.5 + (i % 5) * -2 for i in range(100)], dtype=float)
        rsi = compute_rsi(close, period=14).dropna()
        assert rsi.between(0, 100).all()

    def test_length(self):
        close = pd.Series(range(1, 51), dtype=float)
        assert len(compute_rsi(close, 14)) == len(close)


class TestGarchVol:
    def test_non_negative(self):
        np.random.seed(0)
        close = pd.Series(100 * (1 + 0.01 * np.random.randn(100)))
        vol = compute_garch_vol(close, window=5).dropna()
        assert (vol >= 0).all()


class TestOBI:
    def test_range(self):
        high  = pd.Series([105.0] * 50)
        low   = pd.Series([95.0]  * 50)
        close = pd.Series([100.0 + i * 0.1 for i in range(50)])
        assert compute_obi(high, low, close).between(-1, 1).all()

    def test_boundary(self):
        h, l = pd.Series([110.0]), pd.Series([90.0])
        assert compute_obi(h, l, pd.Series([110.0])).iloc[0] == pytest.approx(1.0)
        assert compute_obi(h, l, pd.Series([90.0])).iloc[0]  == pytest.approx(-1.0)


# ─────────────────────────────────────────────────────────────────────────────
# PAYLOAD SCHEMA TEST
# ─────────────────────────────────────────────────────────────────────────────

def _make_ohlcv(n: int = 400) -> pd.DataFrame:
    np.random.seed(42)
    idx   = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
    close = 30000 + np.cumsum(np.random.randn(n) * 200)
    return pd.DataFrame({
        "Open":   close * 0.999,
        "High":   close * 1.005,
        "Low":    close * 0.995,
        "Close":  close,
        "Volume": np.random.randint(1000, 5000, size=n).astype(float),
    }, index=idx)


class TestPayloadSchema:
    def test_keys_present(self):
        p = _build_payload(_make_ohlcv(), "BTC-USD")
        for key in ("timestamp", "instrument", "features", "ohlcv"):
            assert key in p
        for fkey in ("frac_diff_price_1d", "garch_vol", "order_book_imbalance", "rsi_14"):
            assert fkey in p["features"]
        for okey in ("open", "high", "low", "close", "volume"):
            assert okey in p["ohlcv"]

    def test_feature_ranges(self):
        p = _build_payload(_make_ohlcv(), "BTC-USD")
        assert 0 <= p["features"]["rsi_14"] <= 100
        assert -1 <= p["features"]["order_book_imbalance"] <= 1
        assert p["features"]["garch_vol"] >= 0


# ─────────────────────────────────────────────────────────────────────────────
# ALPACA FEED TEST (mocked HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestAlpacaFeed:
    def _mock_response(self, rows):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = {"bars": rows, "next_page_token": None}
        return mock

    def _make_bars(self, n=300):
        np.random.seed(1)
        close = 180 + np.cumsum(np.random.randn(n))
        dates = pd.date_range("2024-01-01", periods=n, freq="D", tz="UTC")
        return [
            {
                "t": d.isoformat(),
                "o": round(c * 0.999, 2),
                "h": round(c * 1.003, 2),
                "l": round(c * 0.997, 2),
                "c": round(c, 2),
                "v": 1_000_000,
            }
            for d, c in zip(dates, close)
        ]

    @patch("requests.get")
    @patch("config.ALPACA_API_KEY", "TEST_KEY")
    @patch("config.ALPACA_API_SECRET", "TEST_SECRET")
    def test_fetch_returns_dataframe(self, mock_get):
        mock_get.return_value = self._mock_response(self._make_bars())
        import importlib
        import data_pipeline.pipeline as dp_mod
        importlib.reload(dp_mod)          # reload so patched config is picked up
        feed = dp_mod.AlpacaFeed()
        df = feed.fetch("AAPL")
        assert not df.empty
        assert list(df.columns) == ["Open", "High", "Low", "Close", "Volume"]

    @patch("requests.get")
    @patch("config.ALPACA_API_KEY", "TEST_KEY")
    @patch("config.ALPACA_API_SECRET", "TEST_SECRET")
    def test_full_pipeline_stock(self, mock_get):
        mock_get.return_value = self._mock_response(self._make_bars(400))
        import importlib
        import data_pipeline.pipeline as dp_mod
        importlib.reload(dp_mod)
        feed = dp_mod.AlpacaFeed()
        df = feed.fetch("AAPL")
        p = dp_mod._build_payload(df, "AAPL")
        assert p["instrument"] == "AAPL"
        assert 0 <= p["features"]["rsi_14"] <= 100


# ─────────────────────────────────────────────────────────────────────────────
# BINANCE FEED TEST (mocked HTTP)
# ─────────────────────────────────────────────────────────────────────────────

class TestBinanceFeed:
    def _make_klines(self, n=300):
        np.random.seed(2)
        close = 50000 + np.cumsum(np.random.randn(n) * 300)
        base_ms = 1_700_000_000_000
        return [
            [
                base_ms + i * 86_400_000,       # open_time
                str(round(c * 0.999, 2)),        # open
                str(round(c * 1.005, 2)),        # high
                str(round(c * 0.995, 2)),        # low
                str(round(c, 2)),                # close
                str(1000 + i),                   # volume
                base_ms + (i + 1) * 86_400_000, # close_time
                "0", "100", "0", "0", "0",
            ]
            for i, c in enumerate(close)
        ]

    @patch("requests.get")
    def test_fetch_returns_dataframe(self, mock_get):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.return_value = self._make_klines()
        mock_get.return_value = mock
        from data_pipeline.pipeline import BinanceFeed
        feed = BinanceFeed()
        df = feed.fetch("BTC-USD")
        assert not df.empty
        assert "Close" in df.columns

    @patch("requests.get")
    def test_full_pipeline_crypto(self, mock_get):
        mock = MagicMock()
        mock.raise_for_status.return_value = None
        mock.json.side_effect = [self._make_klines(400), []]
        mock_get.return_value = mock
        from data_pipeline.pipeline import BinanceFeed, _build_payload
        feed = BinanceFeed()
        df = feed.fetch("BTC-USD")
        p = _build_payload(df, "BTC-USD")
        assert p["instrument"] == "BTC-USD"
        assert -1 <= p["features"]["order_book_imbalance"] <= 1
