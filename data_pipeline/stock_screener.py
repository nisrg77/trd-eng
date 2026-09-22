"""
data_pipeline/stock_screener.py — Real-Time US Equities Screener & Ranking

- Pre-loads 55 proxy tickers for CME Single Stock Futures.
- RVOL Filter: Uses 5-minute bars to filter out any ticker with RVOL < 1.5 against a 10-day historical session average.
- Cross-Sectional Momentum: Ranks by trailing 15m and 30m percentage returns.
- Output: Returns exactly ONE Long candidate (#1 rank) and ONE Short candidate (#55 rank).
"""

import os
import sys
import time
import logging
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger(__name__)

CME_SSF_55_PROXIES = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK.B", "JPM", "JNJ",
    "V", "PG", "UNH", "HD", "MA", "DIS", "PYPL", "BAC", "VZ", "ADBE",
    "CMCSA", "NFLX", "KO", "NKE", "MRK", "PEP", "T", "PFE", "INTC", "WMT",
    "CRM", "ABT", "ORCL", "ABBV", "CSCO", "TMO", "AVGO", "XOM", "ACN", "QCOM",
    "COST", "CVX", "LLY", "MCD", "DHR", "MDT", "NEE", "TXN", "HON", "UPS",
    "LIN", "BMY", "UNP", "AMGN", "PM"
]

class StockScreener:
    def __init__(self):
        self.headers = {
            "APCA-API-KEY-ID": config.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET,
            "Accept": "application/json",
        }
        self.base_url = config.ALPACA_DATA_URL
        self._historical_vol_cache = {}

    def _fetch_10_day_avg_volume(self, symbol: str) -> float:
        """Fetch average daily volume over the last 10 trading days."""
        if symbol in self._historical_vol_cache:
            return self._historical_vol_cache[symbol]

        end = datetime.now(timezone.utc).date()
        start = end - timedelta(days=20) # 20 days to ensure 10 trading days
        
        url = f"{self.base_url}/stocks/{symbol}/bars"
        params = {
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10,
            "feed": "iex"
        }
        resp = requests.get(url, headers=self.headers, params=params)
        if resp.status_code != 200:
            return 0.0
            
        bars = resp.json().get("bars", [])
        if not bars:
            return 0.0
            
        volumes = [b['v'] for b in bars]
        avg_vol = sum(volumes) / len(volumes)
        self._historical_vol_cache[symbol] = avg_vol
        return avg_vol

    def get_realtime_metrics(self, symbol: str) -> dict:
        """Fetch today's 5-minute bars to calculate intraday volume and 15m/30m returns."""
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=2) # 2 days to ensure we get today's bars
        
        url = f"{self.base_url}/stocks/{symbol}/bars"
        params = {
            "timeframe": "5Min",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "limit": 100,
            "feed": "iex"
        }
        resp = requests.get(url, headers=self.headers, params=params)
        if resp.status_code != 200:
            return {"volume": 0, "ret_15m": 0.0, "ret_30m": 0.0}
            
        bars = resp.json().get("bars", [])
        if len(bars) < 6: # Need at least 30 mins (6 * 5min)
            return {"volume": sum(b['v'] for b in bars), "ret_15m": 0.0, "ret_30m": 0.0}
            
        current_price = bars[-1]['c']
        price_15m_ago = bars[-4]['c']  # 3 bars ago (15m)
        price_30m_ago = bars[-7]['c']  # 6 bars ago (30m)
        
        ret_15m = (current_price - price_15m_ago) / price_15m_ago if price_15m_ago else 0
        ret_30m = (current_price - price_30m_ago) / price_30m_ago if price_30m_ago else 0
        
        # Calculate today's volume (proxy using recent bars for RVOL)
        volume_today = sum(b['v'] for b in bars[-6:]) 
        
        return {
            "volume": volume_today,
            "ret_15m": ret_15m,
            "ret_30m": ret_30m
        }

    def get_targets(self):
        log.info("[Screener] Running Real-Time Screener for 55 CME SSF Proxies...")
        results = []
        
        for sym in CME_SSF_55_PROXIES:
            avg_daily_vol = self._fetch_10_day_avg_volume(sym)
            if avg_daily_vol == 0:
                continue
                
            intra = self.get_realtime_metrics(sym)
            
            # RVOL Calculation
            # Compare recent 30m volume vs 30m average (Avg Daily / 13)
            avg_30m_vol = avg_daily_vol / 13.0 
            rvol = intra["volume"] / avg_30m_vol if avg_30m_vol > 0 else 0
            
            # Momentum Score
            momentum = (intra["ret_15m"] * 0.5) + (intra["ret_30m"] * 0.5)
            
            results.append({
                "symbol": sym,
                "rvol": rvol,
                "momentum": momentum
            })
            time.sleep(0.05) # Rate limit protection

        df = pd.DataFrame(results)
        
        if df.empty:
            log.warning("[Screener] No data retrieved.")
            return None, None
            
        # 1. RVOL Filter >= 1.5
        filtered_df = df[df['rvol'] >= 1.5].copy()
        log.info(f"[Screener] Tickers passing RVOL >= 1.5 filter: {len(filtered_df)}")
        
        if filtered_df.empty:
            log.warning("[Screener] No tickers passed RVOL filter. Falling back to all tickers for ranking.")
            filtered_df = df.copy()

        # 2. Cross-Sectional Momentum Ranking
        filtered_df = filtered_df.sort_values(by="momentum", ascending=False).reset_index(drop=True)
        
        top_long = filtered_df.iloc[0]["symbol"]
        bottom_short = filtered_df.iloc[-1]["symbol"]
        
        log.info(f"[Screener] Target #1 for Longs: {top_long} (Momentum: {filtered_df.iloc[0]['momentum']:.4f})")
        log.info(f"[Screener] Target #55 for Shorts: {bottom_short} (Momentum: {filtered_df.iloc[-1]['momentum']:.4f})")
        
        return top_long, bottom_short

# Singleton
stock_screener = StockScreener()
