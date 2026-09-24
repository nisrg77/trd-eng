"""
tests/test_stock_strategies.py — Unit tests for US Stocks and Futures strategy plugins
"""

import pytest
import pandas as pd
import numpy as np
from strategies.stocks.orb_breakout import ORBBreakoutStrategy
from strategies.stocks.vpoc_reversion import VPOCReversionStrategy


def _generate_orb_data():
    # 3 opening bars: Range [100.0, 105.0]
    bars = [
        {"open": 101.0, "high": 104.0, "low": 100.0, "close": 103.0, "volume": 1000},
        {"open": 103.0, "high": 105.0, "low": 101.5, "close": 104.0, "volume": 1200},
        {"open": 104.0, "high": 104.5, "low": 102.0, "close": 103.5, "volume": 900},
        {"open": 103.5, "high": 104.0, "low": 102.5, "close": 103.8, "volume": 800},
        {"open": 103.8, "high": 108.0, "low": 103.5, "close": 107.5, "volume": 2500}, # Breakout!
    ]
    return pd.DataFrame(bars)


def test_orb_bullish_breakout():
    strat = ORBBreakoutStrategy(params={"orb_bars": 3, "check_session_hours": False})
    df = _generate_orb_data()
    sig = strat.generate_signal("AAPL", df)

    assert sig is not None
    assert sig.direction == 1.0  # Breakout long
    assert sig.conviction >= 0.75
    assert sig.asset_class == "stock"
    assert sig.symbol == "AAPL"
    assert sig.metadata["trigger"] == "orb_high_breakout"


def test_orb_inside_range_returns_none():
    strat = ORBBreakoutStrategy(params={"orb_bars": 3, "check_session_hours": False})
    df = _generate_orb_data()
    # Modify last bar so it closes inside the [100, 105] range
    df.loc[df.index[-1], "close"] = 103.0
    sig = strat.generate_signal("AAPL", df)

    assert sig is None


def test_vpoc_reversion_overextended():
    strat = VPOCReversionStrategy(params={"min_bars": 10})
    
    # Generate 25 bars with last bar stretched way above VAH
    n = 25
    prices = [100.0] * n
    prices[-1] = 130.0  # extreme extension
    
    df = pd.DataFrame({
        "open": prices,
        "high": [p + 1.0 for p in prices],
        "low": [p - 1.0 for p in prices],
        "close": prices,
        "volume": [1000.0] * n,
        "vpoc": [100.0] * n,
        "vah": [105.0] * n,
        "val": [95.0] * n,
        "atr_14": [2.0] * n,
        "vwap": [100.0] * n
    })

    sig = strat.generate_signal("SPY", df)
    assert sig is not None
    assert sig.direction == -1.0  # Short reversion back to VPOC
    assert sig.asset_class == "stock"
    assert sig.symbol == "SPY"
    assert sig.metadata["trigger"] == "vah_overextension"
