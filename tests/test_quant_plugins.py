"""
tests/test_quant_plugins.py — Unit tests for newly extracted modular quant strategy plugins.
"""

import pytest
import pandas as pd
import numpy as np

from strategies.bollinger_pattern import BollingerPatternStrategy
from strategies.dual_thrust import DualThrustStrategy
from strategies.pair_cointegration import PairCointegrationStrategy
from strategies.heikin_ashi_sar import HeikinAshiSARStrategy
from strategies.strategy_registry import StrategyRegistry
from core.signal_packet import SignalPacket


def generate_mock_ohlcv(n: int = 100, trend: str = "up") -> pd.DataFrame:
    np.random.seed(42)
    base = 100.0
    prices = [base]
    for _ in range(n - 1):
        step = np.random.normal(0.5 if trend == "up" else -0.5, 1.0)
        prices.append(prices[-1] + step)
    
    close = np.array(prices)
    high = close + np.random.uniform(0.1, 1.0, size=n)
    low = close - np.random.uniform(0.1, 1.0, size=n)
    open_p = close + np.random.normal(0.0, 0.5, size=n)
    vol = np.random.uniform(100, 1000, size=n)

    return pd.DataFrame({
        "open": open_p,
        "high": high,
        "low": low,
        "close": close,
        "volume": vol
    })


def test_bollinger_pattern_strategy():
    strat = BollingerPatternStrategy()
    df = generate_mock_ohlcv(60)
    sig = strat.generate_signal("BTC-USD", df)
    # Even if no pattern is triggered, it should return None or a valid SignalPacket cleanly
    if sig:
        assert isinstance(sig, SignalPacket)
        assert sig.symbol == "BTC-USD"
        assert sig.direction in [-1.0, 1.0]


def test_dual_thrust_strategy():
    strat = DualThrustStrategy(params={"k1": 0.1, "k2": 0.1})
    df = generate_mock_ohlcv(60, trend="up")
    sig = strat.generate_signal("BTC-USD", df)
    if sig:
        assert isinstance(sig, SignalPacket)
        assert sig.symbol == "BTC-USD"
        assert -1.0 <= sig.direction <= 1.0


def test_pair_cointegration_strategy():
    strat = PairCointegrationStrategy(params={"window": 30, "entry_zscore": 1.0})
    df = generate_mock_ohlcv(60)
    df["benchmark_close"] = df["close"] * 0.95 + np.random.normal(0, 0.5, len(df))
    sig = strat.generate_signal("ETH-USD", df)
    if sig:
        assert isinstance(sig, SignalPacket)
        assert sig.symbol == "ETH-USD"


def test_heikin_ashi_sar_strategy():
    strat = HeikinAshiSARStrategy()
    df = generate_mock_ohlcv(60, trend="up")
    sig = strat.generate_signal("SOL-USD", df)
    if sig:
        assert isinstance(sig, SignalPacket)
        assert sig.symbol == "SOL-USD"


def test_strategy_registry_integration():
    registry = StrategyRegistry()
    s1 = BollingerPatternStrategy()
    s2 = DualThrustStrategy()
    s3 = PairCointegrationStrategy()
    s4 = HeikinAshiSARStrategy()

    registry.register(s1)
    registry.register(s2)
    registry.register(s3)
    registry.register(s4)

    assert len(registry.list_strategies()) == 4
    df = generate_mock_ohlcv(60)
    signals = registry.evaluate_all("BTC-USD", df)
    assert isinstance(signals, list)
