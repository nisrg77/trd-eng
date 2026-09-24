"""
tests/test_crypto_strategies.py — Unit tests for crypto strategy plugins
"""

import pytest
import pandas as pd
import numpy as np
from strategies.crypto.binh_cluc import BinhClucStrategy
from strategies.crypto.nfi_strategy import NFIStrategy
from strategies.crypto.funding_rate_arb import FundingRateArbStrategy
from strategies.crypto.freqtrade_adapter import FreqtradeAdapter


def _generate_synthetic_crypto_df(n=50, trend="up"):
    np.random.seed(101)
    if trend == "up":
        prices = 50000.0 + np.cumsum(np.abs(np.random.randn(n) * 50.0))
    elif trend == "dip":
        prices = 50000.0 + np.cumsum(np.random.randn(n) * 20.0)
        # Force extreme dip on last bar
        prices[-1] = prices[-2] - 1500.0
    else:
        prices = 50000.0 + np.cumsum(np.random.randn(n) * 20.0)

    volumes = np.random.uniform(10.0, 50.0, n)
    if trend == "dip":
        volumes[-1] = 250.0  # huge volume spike

    df = pd.DataFrame({
        "open": prices * 0.999,
        "high": prices * 1.005,
        "low": prices * 0.995,
        "close": prices,
        "volume": volumes
    })
    return df


def test_binh_cluc_dip_signal():
    strat = BinhClucStrategy()
    df_dip = _generate_synthetic_crypto_df(n=50, trend="dip")
    
    # Run strategy
    sig = strat.generate_signal("BTC-USD", df_dip)
    assert sig is not None
    assert sig.direction == 1.0  # Long bounce
    assert sig.conviction >= 0.70
    assert sig.asset_class == "crypto"
    assert sig.symbol == "BTC-USD"


def test_nfi_momentum_signal():
    strat = NFIStrategy()
    df_up = _generate_synthetic_crypto_df(n=50, trend="up")
    
    sig = strat.generate_signal("BTC-USD", df_up)
    # Even if market is flat/choppy, must return either SignalPacket or None safely
    if sig:
        assert sig.asset_class == "crypto"
        assert -1.0 <= sig.direction <= 1.0


def test_funding_rate_arb():
    strat = FundingRateArbStrategy(params={"min_funding_rate_8h": 0.0003})
    
    # 1. No funding rate -> None
    df = pd.DataFrame({"close": [50000.0], "volume": [10.0]})
    assert strat.generate_signal("BTC-USD", df) is None

    # 2. High funding rate -> Short perp opportunity
    df_high_funding = pd.DataFrame({
        "close": [50000.0],
        "volume": [10.0],
        "funding_rate": [0.0005]  # 0.05% per 8h
    })
    sig = strat.generate_signal("BTC-USD", df_high_funding)
    assert sig is not None
    assert sig.direction == -1.0
    assert sig.conviction >= 0.70
    assert sig.metadata["opportunity"] == "cash_and_carry_short_perp"


class MockFreqtradeClass:
    stoploss = 0.03
    def populate_indicators(self, df, metadata):
        df["rsi"] = 25.0
        return df
    def populate_entry_trend(self, df, metadata):
        df["enter_long"] = 1
        return df


def test_freqtrade_adapter():
    adapter = FreqtradeAdapter(strategy_class=MockFreqtradeClass, strategy_id="mock_ft_01")
    df = pd.DataFrame({"close": [100.0, 101.0, 102.0], "volume": [50.0, 50.0, 50.0]})
    sig = adapter.generate_signal("ETH-USD", df)

    assert sig is not None
    assert sig.strategy_id == "mock_ft_01"
    assert sig.direction == 1.0
    assert sig.suggested_stop_pct == 0.03
