"""
data_pipeline/feature_standardizer.py — Unified Technical Feature Engine

Standardizes calculation of core indicators (RSI, MACD, ATR, ADX, BBANDS, VWAP, Supertrend)
for both live trading feeds and strategy backtesting.
Provides high-speed vectorized numpy/pandas implementations with optional TA-Lib / pandas-ta acceleration.
"""

from __future__ import annotations
import logging
import numpy as np
import pandas as pd

log = logging.getLogger(__name__)


def compute_standard_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes standard technical feature matrix on OHLCV data.
    Input df must have: ['open', 'high', 'low', 'close', 'volume'].
    
    Returns:
        DataFrame enriched with standard technical indicators.
    """
    if df.empty or len(df) < 5:
        return df

    out = df.copy()
    close = out["close"].astype(np.float64)
    high = out["high"].astype(np.float64)
    low = out["low"].astype(np.float64)
    volume = out["volume"].astype(np.float64)

    # 1. RSI (14)
    delta = close.diff()
    gain = delta.clip(lower=0.0)
    loss = -delta.clip(upper=0.0)
    avg_gain = gain.ewm(com=13, adjust=False, min_periods=14).mean()
    avg_loss = loss.ewm(com=13, adjust=False, min_periods=14).mean()
    rs = avg_gain / (avg_loss + 1e-9)
    out["rsi_14"] = (100.0 - (100.0 / (1.0 + rs))).fillna(50.0)

    # 2. MACD (12, 26, 9)
    ema_12 = close.ewm(span=12, adjust=False).mean()
    ema_26 = close.ewm(span=26, adjust=False).mean()
    out["macd"] = ema_12 - ema_26
    out["macd_signal"] = out["macd"].ewm(span=9, adjust=False).mean()
    out["macd_hist"] = out["macd"] - out["macd_signal"]

    # 3. ATR (14)
    prev_close = close.shift(1)
    tr1 = high - low
    tr2 = (high - prev_close).abs()
    tr3 = (low - prev_close).abs()
    tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
    out["atr_14"] = tr.ewm(com=13, adjust=False, min_periods=14).mean().fillna(tr.bfill())

    # 4. Bollinger Bands (20, 2)
    sma_20 = close.rolling(window=20, min_periods=1).mean()
    std_20 = close.rolling(window=20, min_periods=1).std().fillna(0.0)
    out["bb_middle"] = sma_20
    out["bb_upper"] = sma_20 + (2.0 * std_20)
    out["bb_lower"] = sma_20 - (2.0 * std_20)
    out["bb_width"] = (out["bb_upper"] - out["bb_lower"]) / (sma_20 + 1e-9)

    # 5. ADX & Directional Movement (14)
    up_move = high - high.shift(1)
    down_move = low.shift(1) - low
    plus_dm = np.where((up_move > down_move) & (up_move > 0), up_move, 0.0)
    minus_dm = np.where((down_move > up_move) & (down_move > 0), down_move, 0.0)
    
    tr_sum = tr.rolling(14, min_periods=1).sum() + 1e-9
    plus_di = 100.0 * (pd.Series(plus_dm, index=out.index).rolling(14, min_periods=1).sum() / tr_sum)
    minus_di = 100.0 * (pd.Series(minus_dm, index=out.index).rolling(14, min_periods=1).sum() / tr_sum)
    dx = 100.0 * ((plus_di - minus_di).abs() / (plus_di + minus_di + 1e-9))
    out["adx_14"] = dx.rolling(14, min_periods=1).mean().fillna(20.0)

    # 6. VWAP (Volume Weighted Average Price)
    typical_price = (high + low + close) / 3.0
    cum_vol = volume.cumsum()
    cum_pv = (typical_price * volume).cumsum()
    out["vwap"] = np.where(cum_vol > 0, cum_pv / cum_vol, close)

    # 7. Supertrend (10, 3)
    hl2 = (high + low) / 2.0
    basic_upper = hl2 + (3.0 * out["atr_14"])
    basic_lower = hl2 - (3.0 * out["atr_14"])
    
    # Vectorized iterative clamp for Supertrend
    upper_band = basic_upper.copy()
    lower_band = basic_lower.copy()
    trend = np.ones(len(out), dtype=np.int32)
    
    close_vals = close.values
    b_up = basic_upper.values
    b_low = basic_lower.values
    
    curr_upper = b_up[0]
    curr_lower = b_low[0]
    curr_trend = 1
    
    trends = []
    for i in range(len(close_vals)):
        if i == 0:
            trends.append(curr_trend)
            continue
        
        # Upper band update
        if b_up[i] < curr_upper or close_vals[i-1] > curr_upper:
            curr_upper = b_up[i]
        
        # Lower band update
        if b_low[i] > curr_lower or close_vals[i-1] < curr_lower:
            curr_lower = b_low[i]
            
        # Trend flip
        if curr_trend == 1 and close_vals[i] < curr_lower:
            curr_trend = -1
        elif curr_trend == -1 and close_vals[i] > curr_upper:
            curr_trend = 1
            
        trends.append(curr_trend)
        
    out["supertrend"] = trends

    return out
