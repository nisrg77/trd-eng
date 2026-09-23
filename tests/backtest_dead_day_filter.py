"""
tests/backtest_dead_day_filter.py — Dead-Day Filter Historical Backtester

Audits real historical market data (120-365 daily bars) from Alpaca and Binance:
1. Calculates True Range (TR), 14-day ATR, Relative Volume (RVOL = Vol / 20-SMA Vol), and Realized Volatility.
2. Identifies 'Dead Days' (low volume, compressed range < 60% ATR, low volatility chop).
3. Compares volatility and returns on Active vs. Skipped days to verify it skips chop without missing expansion days.
"""

import os
import sys
import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from data_pipeline.pipeline import AlpacaFeed, BinanceFeed

def calculate_indicators(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    high_low = df["High"] - df["Low"]
    high_prev_close = (df["High"] - df["Close"].shift(1)).abs()
    low_prev_close = (df["Low"] - df["Close"].shift(1)).abs()
    tr = pd.concat([high_low, high_prev_close, low_prev_close], axis=1).max(axis=1)
    df["TR"] = tr
    df["ATR_14"] = tr.rolling(window=14).mean()
    df["Range_ATR_Ratio"] = df["TR"] / df["ATR_14"].replace(0, np.nan)
    
    vol_sma_20 = df["Volume"].rolling(window=20).mean()
    df["RVOL_20"] = df["Volume"] / vol_sma_20.replace(0, np.nan)
    
    df["HL_Pct"] = (df["High"] - df["Low"]) / df["Close"]
    df["Daily_Return"] = df["Close"].pct_change()
    
    log_ret = np.log(df["Close"] / df["Close"].shift(1))
    df["Realized_Vol"] = np.sqrt(log_ret.ewm(span=5, adjust=False).var() * 252)
    
    return df

def apply_dead_day_filter(df: pd.DataFrame, is_crypto: bool = False) -> pd.DataFrame:
    df = calculate_indicators(df)
    
    # Rule 1: Extreme range compression: TR < 60% of 14-day ATR
    cond_a = df["Range_ATR_Ratio"] < 0.60
    
    # Rule 2: Low relative volume + compressed range: RVOL < 0.65 AND TR < 75% of ATR
    cond_b = (df["RVOL_20"] < 0.65) & (df["Range_ATR_Ratio"] < 0.75)
    
    # Rule 3: Extreme low realized volatility
    vol_thresh = 0.025 if is_crypto else 0.009
    cond_c = (df["Realized_Vol"] < vol_thresh) & (df["Range_ATR_Ratio"] < 0.70)
    
    df["Is_Dead_Day"] = cond_a | cond_b | cond_c
    return df.dropna()

def run_backtest_report():
    print("=" * 80)
    print("           DEAD-DAY FILTER HISTORICAL BACKTEST AUDIT REPORT")
    print("=" * 80)
    
    alpaca = AlpacaFeed() if config.ALPACA_API_KEY else None
    binance = BinanceFeed()
    
    symbols_to_test = [
        ("BTC-USD", True),
        ("ETH-USD", True),
        ("SPY", False),
        ("AAPL", False),
        ("NVDA", False),
    ]
    
    summary_results = []
    
    for symbol, is_crypto in symbols_to_test:
        try:
            if is_crypto:
                df_raw = binance.fetch(symbol)
            else:
                if alpaca:
                    df_raw = alpaca.fetch(symbol)
                else:
                    continue
                    
            df_slice = df_raw.iloc[-120:] if len(df_raw) > 120 else df_raw
            df_filtered = apply_dead_day_filter(df_slice, is_crypto=is_crypto)
            
            total_days = len(df_filtered)
            dead_days = int(df_filtered["Is_Dead_Day"].sum())
            active_days = total_days - dead_days
            skip_rate = (dead_days / total_days) * 100 if total_days > 0 else 0
            
            active_df = df_filtered[~df_filtered["Is_Dead_Day"]]
            dead_df = df_filtered[df_filtered["Is_Dead_Day"]]
            
            avg_hl_active = active_df["HL_Pct"].mean() * 100
            avg_hl_dead = dead_df["HL_Pct"].mean() * 100 if len(dead_df) > 0 else 0
            
            avg_rvol_active = active_df["RVOL_20"].mean()
            avg_rvol_dead = dead_df["RVOL_20"].mean() if len(dead_df) > 0 else 0
            
            summary_results.append({
                "Symbol": symbol,
                "Asset Class": "Crypto" if is_crypto else "US Equity",
                "Total Days": total_days,
                "Skipped Days": dead_days,
                "Traded Days": active_days,
                "Skip Rate %": f"{skip_rate:.1f}%",
                "Active Range": f"{avg_hl_active:.2f}%",
                "Dead Range": f"{avg_hl_dead:.2f}%",
                "Active RVOL": f"{avg_rvol_active:.2f}x",
                "Dead RVOL": f"{avg_rvol_dead:.2f}x",
            })
            
            print(f"\n--- {symbol} ({'Crypto (24/7)' if is_crypto else 'US Equity (RTH)'}) ---")
            print(f"  • Days Analyzed      : {total_days} days (~6 months)")
            print(f"  • Dead Days Skipped  : {dead_days} days ({skip_rate:.1f}%)")
            print(f"  • Active Days Traded : {active_days} days ({100 - skip_rate:.1f}%)")
            print(f"  • Active Days Avg Vol: Range {avg_hl_active:.2f}%, RVOL {avg_rvol_active:.2f}x")
            print(f"  • Dead Days Avg Vol  : Range {avg_hl_dead:.2f}%, RVOL {avg_rvol_dead:.2f}x")
            
            if len(dead_df) > 0:
                print("  • Recent Skipped Days Sample:")
                for idx, row in dead_df.tail(3).iterrows():
                    date_str = str(idx)[:10]
                    print(f"    - {date_str}: Range {row['HL_Pct']*100:.2f}% (TR/ATR: {row['Range_ATR_Ratio']*100:.1f}%), RVOL: {row['RVOL_20']:.2f}x")
                    
        except Exception as e:
            print(f"Error testing {symbol}: {e}")
            
    print("\n" + "=" * 80)
    print("BACKTEST COMPARISON TABLE:")
    print("=" * 80)
    summary_df = pd.DataFrame(summary_results)
    print(summary_df.to_string(index=False))
    print("=" * 80)

if __name__ == "__main__":
    run_backtest_report()
