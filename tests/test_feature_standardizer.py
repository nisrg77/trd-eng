"""
tests/test_feature_standardizer.py — Tests for standard technical feature engine
"""

import pytest
import pandas as pd
import numpy as np
from data_pipeline.feature_standardizer import compute_standard_features


def test_standard_feature_generation():
    np.random.seed(42)
    n = 60
    base_price = 100.0 + np.cumsum(np.random.randn(n) * 1.5)
    
    df = pd.DataFrame({
        "open": base_price + np.random.randn(n) * 0.2,
        "high": base_price + np.abs(np.random.randn(n) * 0.8),
        "low": base_price - np.abs(np.random.randn(n) * 0.8),
        "close": base_price,
        "volume": np.random.uniform(500, 2000, n),
    })

    enriched = compute_standard_features(df)

    # Check columns
    expected_cols = [
        "rsi_14", "macd", "macd_signal", "macd_hist",
        "atr_14", "bb_upper", "bb_middle", "bb_lower", "bb_width",
        "adx_14", "vwap", "supertrend"
    ]
    for col in expected_cols:
        assert col in enriched.columns, f"Missing expected feature {col}"

    # Range and sanity checks
    assert enriched["rsi_14"].between(0.0, 100.0).all()
    assert (enriched["atr_14"] >= 0.0).all()
    assert (enriched["bb_upper"] >= enriched["bb_lower"]).all()
    assert enriched["supertrend"].isin([-1, 1]).all()
    assert not enriched[expected_cols].isna().any().any()
