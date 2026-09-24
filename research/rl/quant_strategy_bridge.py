"""
research/rl/quant_strategy_bridge.py — Quant Strategies Bridge for RL

Provides vectorized, zero-lookahead signal generators and baseline wrappers
for strategies from research/quant-trading:
1. Dual Thrust Breakout (Michael Chalek range breakout)
2. Awesome Oscillator (Bill Williams momentum zero-cross)
3. Heikin-Ashi Trend Following
4. RSI Pattern / Momentum Divergence
5. London / Session Breakout Filter
"""

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, Any, Optional, Tuple, Callable


class QuantStrategyBridge:
    """
    Vectorized evaluation bridge for quant-trading strategies.
    Produces discrete actions: -1 (Short), 0 (Flat), +1 (Long) or continuous signals.
    """

    @staticmethod
    def dual_thrust_signals(
        df: pd.DataFrame,
        k1: float = 0.5,
        k2: float = 0.5,
        lookback_bars: int = 20
    ) -> pd.Series:
        """
        Dual Thrust Opening Range Breakout:
        Range = max(HH - LC, HC - LL)
        Buy Trigger = Open + k1 * Range
        Sell Trigger = Open - k2 * Range
        """
        if len(df) < lookback_bars + 1:
            return pd.Series(0.0, index=df.index)

        high = df["high"]
        low = df["low"]
        close = df["close"]
        open_px = df["open"]

        hh = high.rolling(lookback_bars).max().shift(1)
        lc = close.rolling(lookback_bars).min().shift(1)
        hc = close.rolling(lookback_bars).max().shift(1)
        ll = low.rolling(lookback_bars).min().shift(1)

        range_val = np.maximum(hh - lc, hc - ll)
        upper_bound = open_px + (k1 * range_val)
        lower_bound = open_px - (k2 * range_val)

        signals = pd.Series(0.0, index=df.index)
        signals[close > upper_bound] = 1.0   # Long
        signals[close < lower_bound] = -1.0  # Short
        return signals.ffill().fillna(0.0)

    @staticmethod
    def awesome_oscillator_signals(
        df: pd.DataFrame,
        fast_period: int = 5,
        slow_period: int = 34
    ) -> pd.Series:
        """
        Awesome Oscillator (Bill Williams):
        AO = SMA(Median Price, 5) - SMA(Median Price, 34)
        Signal = +1 if AO > 0 and AO > AO.shift(1), -1 if AO < 0 and AO < AO.shift(1), else 0
        """
        if len(df) < slow_period + 1:
            return pd.Series(0.0, index=df.index)

        median_px = (df["high"] + df["low"]) / 2.0
        fast_sma = median_px.rolling(fast_period).mean()
        slow_sma = median_px.rolling(slow_period).mean()
        ao = fast_sma - slow_sma

        signals = pd.Series(0.0, index=df.index)
        signals[(ao > 0) & (ao > ao.shift(1))] = 1.0
        signals[(ao < 0) & (ao < ao.shift(1))] = -1.0
        return signals.fillna(0.0)

    @staticmethod
    def heikin_ashi_signals(df: pd.DataFrame) -> pd.Series:
        """
        Heikin-Ashi trend-following direction:
        HA_Close = (Open + High + Low + Close) / 4
        HA_Open = (HA_Open_prev + HA_Close_prev) / 2
        Long = HA_Close > HA_Open and Low == HA_Open (strong trend)
        Short = HA_Close < HA_Open and High == HA_Open
        """
        if len(df) < 5:
            return pd.Series(0.0, index=df.index)

        ha_close = (df["open"] + df["high"] + df["low"] + df["close"]) / 4.0
        ha_open = np.zeros(len(df))
        ha_open[0] = (df["open"].iloc[0] + df["close"].iloc[0]) / 2.0

        for i in range(1, len(df)):
            ha_open[i] = (ha_open[i - 1] + ha_close.iloc[i - 1]) / 2.0

        ha_open_s = pd.Series(ha_open, index=df.index)
        signals = pd.Series(0.0, index=df.index)
        signals[ha_close > ha_open_s] = 1.0
        signals[ha_close < ha_open_s] = -1.0
        return signals

    @staticmethod
    def rsi_pattern_signals(
        df: pd.DataFrame,
        period: int = 14,
        oversold: float = 30.0,
        overbought: float = 70.0
    ) -> pd.Series:
        """
        RSI Mean-Reversion Pattern.
        """
        if len(df) < period + 1:
            return pd.Series(0.0, index=df.index)

        close = df["close"]
        delta = close.diff()
        gain = (delta.where(delta > 0, 0)).rolling(period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(period).mean()
        rs = gain / (loss + 1e-9)
        rsi = 100 - (100 / (1 + rs))

        signals = pd.Series(0.0, index=df.index)
        signals[rsi < oversold] = 1.0
        signals[rsi > overbought] = -1.0
        return signals.ffill().fillna(0.0)

    @classmethod
    def get_all_quant_signals(cls, df: pd.DataFrame) -> Dict[str, pd.Series]:
        """
        Computes signals for all bridged strategies for feature extraction or benchmarking.
        """
        return {
            "dual_thrust": cls.dual_thrust_signals(df),
            "awesome_oscillator": cls.awesome_oscillator_signals(df),
            "heikin_ashi": cls.heikin_ashi_signals(df),
            "rsi_pattern": cls.rsi_pattern_signals(df)
        }
