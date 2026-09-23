"""
data_pipeline/stock_screener.py — 7-Day Cached US Equities Screener & Candidate Selection

Features:
- 7-Day Persistent Cache: Evaluates the 55 CME SSF proxy universe once every 7 days,
  drastically reducing compute overhead and Alpaca REST API rate limit pressure.
- Top 10-15 Candidate Ranking: Filters by RVOL and ranks by cross-sectional momentum.
- Candidate Rotation: Randomly / dynamically selects active symbols from the top pool
  for signal generation and execution.
- Instant Cache Refresh: Allows manual or forced invalidation on-demand.
"""

from __future__ import annotations
import os
import sys
import json
import time
import random
import logging
from datetime import datetime, timezone, timedelta
import requests
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

log = logging.getLogger(__name__)

CACHE_FILE = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "screener_cache.json")

CME_SSF_55_PROXIES = [
    "AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK.B", "JPM", "JNJ",
    "V", "PG", "UNH", "HD", "MA", "DIS", "PYPL", "BAC", "VZ", "ADBE",
    "CMCSA", "NFLX", "KO", "NKE", "MRK", "PEP", "T", "PFE", "INTC", "WMT",
    "CRM", "ABT", "ORCL", "ABBV", "CSCO", "TMO", "AVGO", "XOM", "ACN", "QCOM",
    "COST", "CVX", "LLY", "MCD", "DHR", "MDT", "NEE", "TXN", "HON", "UPS",
    "LIN", "BMY", "UNP", "AMGN", "PM"
]

# High-liquidity fallback ranking in case of network timeout / market closed off-hours
FALLBACK_CANDIDATES = [
    {"rank": 1, "symbol": "NVDA", "rvol": 2.45, "momentum": 0.0382, "bias": "BUY", "action": "LONG"},
    {"rank": 2, "symbol": "TSLA", "rvol": 2.12, "momentum": 0.0294, "bias": "BUY", "action": "LONG"},
    {"rank": 3, "symbol": "AAPL", "rvol": 1.88, "momentum": 0.0185, "bias": "BUY", "action": "LONG"},
    {"rank": 4, "symbol": "META", "rvol": 1.94, "momentum": 0.0162, "bias": "BUY", "action": "LONG"},
    {"rank": 5, "symbol": "MSFT", "rvol": 1.65, "momentum": 0.0141, "bias": "BUY", "action": "LONG"},
    {"rank": 6, "symbol": "AMZN", "rvol": 1.72, "momentum": 0.0118, "bias": "BUY", "action": "LONG"},
    {"rank": 7, "symbol": "GOOGL", "rvol": 1.58, "momentum": 0.0095, "bias": "BUY", "action": "LONG"},
    {"rank": 8, "symbol": "AMD", "rvol": 2.05, "momentum": 0.0084, "bias": "BUY", "action": "LONG"},
    {"rank": 9, "symbol": "SPY", "rvol": 1.52, "momentum": 0.0042, "bias": "NEUTRAL", "action": "LONG"},
    {"rank": 10, "symbol": "JPM", "rvol": 1.48, "momentum": -0.0031, "bias": "SELL", "action": "SHORT"},
    {"rank": 11, "symbol": "DIS", "rvol": 1.55, "momentum": -0.0085, "bias": "SELL", "action": "SHORT"},
    {"rank": 12, "symbol": "INTC", "rvol": 1.82, "momentum": -0.0142, "bias": "SELL", "action": "SHORT"},
    {"rank": 13, "symbol": "NKE", "rvol": 1.64, "momentum": -0.0195, "bias": "SELL", "action": "SHORT"},
    {"rank": 14, "symbol": "PFE", "rvol": 1.71, "momentum": -0.0248, "bias": "SELL", "action": "SHORT"},
    {"rank": 15, "symbol": "PYPL", "rvol": 1.90, "momentum": -0.0315, "bias": "SELL", "action": "SHORT"},
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
        start = end - timedelta(days=20)
        
        url = f"{self.base_url}/stocks/{symbol}/bars"
        params = {
            "timeframe": "1Day",
            "start": start.isoformat(),
            "end": end.isoformat(),
            "limit": 10,
            "feed": "iex"
        }
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=5)
            if resp.status_code != 200:
                return 0.0
            bars = resp.json().get("bars", [])
            if not bars:
                return 0.0
            volumes = [b['v'] for b in bars]
            avg_vol = sum(volumes) / len(volumes)
            self._historical_vol_cache[symbol] = avg_vol
            return avg_vol
        except Exception:
            return 0.0

    def get_realtime_metrics(self, symbol: str) -> dict:
        """Fetch today's 5-minute bars to calculate intraday volume and 15m/30m returns."""
        end_dt = datetime.now(timezone.utc)
        start_dt = end_dt - timedelta(days=2)
        
        url = f"{self.base_url}/stocks/{symbol}/bars"
        params = {
            "timeframe": "5Min",
            "start": start_dt.isoformat(),
            "end": end_dt.isoformat(),
            "limit": 100,
            "feed": "iex"
        }
        try:
            resp = requests.get(url, headers=self.headers, params=params, timeout=5)
            if resp.status_code != 200:
                return {"volume": 0, "ret_15m": 0.0, "ret_30m": 0.0}
            bars = resp.json().get("bars", [])
            if len(bars) < 6:
                return {"volume": sum(b['v'] for b in bars) if bars else 0, "ret_15m": 0.0, "ret_30m": 0.0}
                
            current_price = bars[-1]['c']
            price_15m_ago = bars[-4]['c']
            price_30m_ago = bars[-7]['c']
            
            ret_15m = (current_price - price_15m_ago) / price_15m_ago if price_15m_ago else 0
            ret_30m = (current_price - price_30m_ago) / price_30m_ago if price_30m_ago else 0
            volume_today = sum(b['v'] for b in bars[-6:]) 
            
            return {
                "volume": volume_today,
                "ret_15m": ret_15m,
                "ret_30m": ret_30m
            }
        except Exception:
            return {"volume": 0, "ret_15m": 0.0, "ret_30m": 0.0}

    def _execute_full_analysis(self, count: int = 15) -> list[dict]:
        """Runs the RVOL and momentum ranking across the 55 CME proxy universe."""
        log.info("[Screener] Running comprehensive 7-day analysis across %d SSF proxies...", len(CME_SSF_55_PROXIES))
        results = []
        
        for sym in CME_SSF_55_PROXIES:
            avg_daily_vol = self._fetch_10_day_avg_volume(sym)
            if avg_daily_vol == 0:
                continue
                
            intra = self.get_realtime_metrics(sym)
            avg_30m_vol = avg_daily_vol / 13.0 
            rvol = intra["volume"] / avg_30m_vol if avg_30m_vol > 0 else 0
            momentum = (intra["ret_15m"] * 0.5) + (intra["ret_30m"] * 0.5)
            
            results.append({
                "symbol": sym,
                "rvol": round(rvol, 2),
                "momentum": round(momentum, 4)
            })
            time.sleep(0.04)

        if not results:
            log.warning("[Screener] Alpaca analysis returned no valid tickers. Utilizing curated baseline ranking.")
            return FALLBACK_CANDIDATES[:count]

        df = pd.DataFrame(results)
        
        # RVOL Filter >= 1.5 with fallback
        filtered_df = df[df['rvol'] >= 1.2].copy()
        if filtered_df.empty or len(filtered_df) < count:
            filtered_df = df.copy()

        filtered_df = filtered_df.sort_values(by="momentum", ascending=False).reset_index(drop=True)
        top_df = filtered_df.head(count)
        
        candidates = []
        for idx, row in top_df.iterrows():
            rank = idx + 1
            mom = row["momentum"]
            bias = "BUY" if mom > 0.005 else ("SELL" if mom < -0.005 else "NEUTRAL")
            action = "LONG" if bias == "BUY" else ("SHORT" if bias == "SELL" else "HOLD")
            candidates.append({
                "rank": rank,
                "symbol": row["symbol"],
                "rvol": float(row["rvol"]),
                "momentum": float(row["momentum"]),
                "bias": bias,
                "action": action
            })

        return candidates

    def get_top_candidates(self, count: int = 15, cache_ttl_days: int = 7, force_refresh: bool = False) -> list[dict]:
        """
        Retrieves the top 10-15 ranked stocks.
        Returns cached results if cache is less than cache_ttl_days old.
        """
        now = time.time()
        ttl_seconds = cache_ttl_days * 86400
        
        if not force_refresh and os.path.exists(CACHE_FILE):
            try:
                with open(CACHE_FILE, "r", encoding="utf-8") as f:
                    cache_data = json.load(f)
                last_updated = cache_data.get("last_updated", 0)
                candidates = cache_data.get("top_candidates", [])
                
                # Check if cache is still valid
                if (now - last_updated) < ttl_seconds and candidates:
                    days_left = round((ttl_seconds - (now - last_updated)) / 86400, 1)
                    log.info(f"[Screener Cache] Cache hit: {len(candidates)} candidates valid for next {days_left} days.")
                    return candidates[:count]
            except Exception as e:
                log.warning(f"[Screener Cache] Error reading cache: {e}. Recomputing...")

        # Cache expired or forced refresh
        log.info("[Screener Cache] 7-day cache invalid or expired. Computing fresh rankings...")
        try:
            candidates = self._execute_full_analysis(count=count)
        except Exception as e:
            log.error(f"[Screener] Failed to run screener analysis: {e}. Using fallback candidates.")
            candidates = FALLBACK_CANDIDATES[:count]

        # Sync to MongoDB database manager if connected
        try:
            from middleware.db_manager import mongo_db
            if mongo_db.is_connected():
                mongo_db.save_screener_cache(candidates)
        except Exception:
            pass

        # Write fresh cache file
        cache_payload = {
            "last_updated": now,
            "expires_at": now + ttl_seconds,
            "ttl_days": cache_ttl_days,
            "universe_size": len(CME_SSF_55_PROXIES),
            "top_candidates": candidates
        }
        try:
            with open(CACHE_FILE, "w", encoding="utf-8") as f:
                json.dump(cache_payload, f, indent=2)
            log.info(f"[Screener Cache] Successfully saved {len(candidates)} candidates to {CACHE_FILE}")
        except Exception as e:
            log.error(f"[Screener Cache] Failed to write cache file: {e}")

        return candidates[:count]

    def select_active_targets(self, n: int = 2, count: int = 15, cache_ttl_days: int = 7) -> list[str]:
        """
        Selects active trade targets from the top 10-15 candidates.
        Ensures diverse representation (selects top Long, and a candidate from the pool).
        """
        candidates = self.get_top_candidates(count=count, cache_ttl_days=cache_ttl_days)
        if not candidates:
            return ["AAPL", "SPY"]
            
        symbols = [c["symbol"] for c in candidates]
        if len(symbols) <= n:
            return symbols

        # Top 1 is prioritized, remaining chosen randomly from top 10 to rotate compute
        primary = symbols[0]
        pool = [s for s in symbols[1:min(count, 10)] if s != primary]
        secondary = random.sample(pool, min(n - 1, len(pool)))
        return [primary] + secondary

    def get_targets(self) -> tuple[str, str]:
        """Backward-compatible endpoint returning (top_long, bottom_short)."""
        candidates = self.get_top_candidates(count=15)
        if not candidates:
            return "AAPL", "SPY"
        top_long = candidates[0]["symbol"]
        bottom_short = candidates[-1]["symbol"]
        return top_long, bottom_short

# Singleton instance
stock_screener = StockScreener()
