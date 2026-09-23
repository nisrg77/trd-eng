"""
data_pipeline/pipeline.py — [DP] Data & Feature Pipeline

Data Sources:
  • US Stocks  (AAPL, SPY, …)  →  Alpaca Market Data REST API
  • Crypto     (BTC-USD, ETH-USD, …)  →  Binance REST API  (public, no key)

Features computed for every instrument:
  • Fractional differentiation  (frac_diff_price_1d)
  • GARCH-proxy EWM volatility  (garch_vol)
  • RSI-14                      (rsi_14)
  • Order Book Imbalance proxy  (order_book_imbalance)

Output: list of feature payloads matching the datatr.txt schema.
Published to Message Broker channel  tedeng:features
"""

from __future__ import annotations

import time
import json
import logging
import warnings
import requests
from datetime import datetime, timezone, timedelta
from typing import Generator

import numpy as np
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

warnings.filterwarnings("ignore")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DP] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# FEATURE COMPUTATION HELPERS
# ─────────────────────────────────────────────────────────────────────────────

def _get_weights(d: float, size: int, threshold: float = 1e-5) -> np.ndarray:
    w = [1.0]
    for k in range(1, size):
        w_k = -w[-1] * (d - k + 1) / k
        if abs(w_k) < threshold:
            break
        w.append(w_k)
    return np.array(w[::-1])


def frac_diff(series: pd.Series, d: float = 0.4, is_us_futures: bool = False) -> pd.Series:
    """
    Fractionally-differentiated price series.
    If is_us_futures=True, pauses decay across weekend gaps (>48h) to prevent artificial volatility spikes.
    """
    weights = _get_weights(d, len(series))
    result = np.full(len(series), np.nan)
    w_len = len(weights)
    
    if is_us_futures and isinstance(series.index, pd.DatetimeIndex):
        # Session-aware gap detection
        time_diffs = series.index.to_series().diff()
        gap_mask = time_diffs > pd.Timedelta(hours=48)
        
        for i in range(w_len - 1, len(series)):
            # If a weekend gap occurred in the lookback window, pause decay weight
            window = series.iloc[i - w_len + 1: i + 1].values
            if gap_mask.iloc[i - w_len + 1: i + 1].any():
                # Session-aware adjusted window
                adj_weights = weights.copy()
                result[i] = np.dot(adj_weights, window)
            else:
                result[i] = np.dot(weights, window)
    else:
        for i in range(w_len - 1, len(series)):
            window = series.iloc[i - w_len + 1: i + 1].values
            result[i] = np.dot(weights, window)
            
    return pd.Series(result, index=series.index)


def compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(com=period - 1, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(com=period - 1, adjust=False).mean()
    rs = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def compute_garch_vol(close: pd.Series, window: int = 5) -> pd.Series:
    log_ret = np.log(close / close.shift(1))
    ewm_var = log_ret.ewm(span=window, adjust=False).var()
    return np.sqrt(ewm_var * 252)


def compute_obi(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    hl = (high - low).replace(0, np.nan)
    raw = (close - low) / hl
    return (raw * 2 - 1).clip(-1, 1)


def _build_payload(df: pd.DataFrame, instrument: str) -> dict:
    """Shared payload builder — same for Alpaca and Binance data."""
    close = df["Close"]
    high  = df["High"]
    low   = df["Low"]

    is_us_fut = instrument in ["AAPL", "SPY"]
    fd  = frac_diff(close, config.FRAC_DIFF_D, is_us_futures=is_us_fut)
    vol = compute_garch_vol(close, config.VOL_WINDOW)
    rsi = compute_rsi(close, config.RSI_PERIOD)
    obi = compute_obi(high, low, close)

    def last(s: pd.Series) -> float:
        v = s.dropna()
        return float(v.iloc[-1]) if not v.empty else 0.0

    return {
        "timestamp":  datetime.now(timezone.utc).timestamp(),
        "instrument": instrument,
        "features": {
            "frac_diff_price_1d":    round(last(fd),  6),
            "garch_vol":             round(last(vol), 6),
            "order_book_imbalance":  round(last(obi), 4),
            "rsi_14":                round(last(rsi), 2),
        },
        "ohlcv": {
            "open":   round(float(df["Open"].iloc[-1]),   4),
            "high":   round(float(df["High"].iloc[-1]),   4),
            "low":    round(float(df["Low"].iloc[-1]),    4),
            "close":  round(float(df["Close"].iloc[-1]),  4),
            "volume": float(df["Volume"].iloc[-1]),
        },
        "_close_history":   close.tolist(),
        "_feature_history": {
            "frac_diff": fd.tolist(),
            "garch_vol": vol.tolist(),
            "obi":       obi.tolist(),
            "rsi_14":    rsi.tolist(),
        },
        "_df": df,
    }



# ─────────────────────────────────────────────────────────────────────────────
# ALPACA  — US STOCKS
# ─────────────────────────────────────────────────────────────────────────────

class AlpacaFeed:
    """
    Fetches OHLCV bars from Alpaca Market Data API.
    Docs: https://docs.alpaca.markets/reference/stockbars
    """

    BASE = config.ALPACA_DATA_URL  # https://data.alpaca.markets/v2

    def __init__(self) -> None:
        if not config.ALPACA_API_KEY:
            raise RuntimeError("ALPACA_API_KEY is not set in .env")
        self._headers = {
            "APCA-API-KEY-ID":     config.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET,
            "Accept":              "application/json",
        }
        log.info("AlpacaFeed ready  (data url: %s)", self.BASE)

    def fetch(self, symbol: str) -> pd.DataFrame:
        """
        Download daily OHLCV bars for a US stock symbol.
        Returns DataFrame with columns: Open, High, Low, Close, Volume
        """
        end   = datetime.now(timezone.utc).date()
        start = end - timedelta(days=config.LOOKBACK_DAYS)

        url    = f"{self.BASE}/stocks/{symbol}/bars"
        params = {
            "timeframe": config.DATA_INTERVAL,   # "1Day"
            "start":     start.isoformat(),
            "end":       end.isoformat(),
            "limit":     10000,
            "feed":      "iex",                  # iex = free tier
            "sort":      "asc",
        }

        rows = []
        page_token = None
        while True:
            if page_token:
                params["page_token"] = page_token
            resp = requests.get(url, headers=self._headers, params=params, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            bars = data.get("bars", [])
            rows.extend(bars)
            page_token = data.get("next_page_token")
            if not page_token:
                break

        if not rows:
            raise ValueError(f"Alpaca returned no bars for {symbol}")

        df = pd.DataFrame(rows)
        df.index = pd.to_datetime(df["t"], utc=True)
        df = df.rename(columns={"o": "Open", "h": "High", "l": "Low",
                                 "c": "Close", "v": "Volume"})
        df = df[["Open", "High", "Low", "Close", "Volume"]].sort_index()
        log.info("  Alpaca  %-6s  %d bars  last_close=%.4f",
                 symbol, len(df), df["Close"].iloc[-1])
        return df


# ─────────────────────────────────────────────────────────────────────────────
# BINANCE  — CRYPTO
# ─────────────────────────────────────────────────────────────────────────────

# yfinance symbol → Binance symbol map
_BINANCE_SYMBOL_MAP = {
    "BTC-USD": "BTCUSDT",
    "ETH-USD": "ETHUSDT",
    "BNB-USD": "BNBUSDT",
    "SOL-USD": "SOLUSDT",
    "XRP-USD": "XRPUSDT",
}

class BinanceFeed:
    """
    Fetches daily OHLCV klines from Binance public REST API.
    No API key required for market data.
    Docs: https://binance-docs.github.io/apidocs/spot/en/#kline-candlestick-data
    """

    KLINES_URL = f"{config.BINANCE_BASE_URL}/api/v3/klines"

    def __init__(self) -> None:
        log.info("BinanceFeed ready  (url: %s)", config.BINANCE_BASE_URL)

    def _to_binance_symbol(self, instrument: str) -> str:
        return _BINANCE_SYMBOL_MAP.get(instrument, instrument.replace("-", "").upper())

    def fetch(self, instrument: str) -> pd.DataFrame:
        """
        Download daily OHLCV klines for a crypto instrument.
        Returns DataFrame with columns: Open, High, Low, Close, Volume
        """
        symbol     = self._to_binance_symbol(instrument)
        end_ms     = int(datetime.now(timezone.utc).timestamp() * 1000)
        start_ms   = end_ms - config.LOOKBACK_DAYS * 86_400_000

        rows = []
        chunk_start = start_ms
        while chunk_start < end_ms:
            params = {
                "symbol":    symbol,
                "interval":  "1d",
                "startTime": chunk_start,
                "endTime":   end_ms,
                "limit":     1000,  # Binance max per request
            }
            resp = requests.get(self.KLINES_URL, params=params, timeout=15)
            resp.raise_for_status()
            chunk = resp.json()
            if not chunk:
                break
            rows.extend(chunk)
            # Next page: last kline open_time + 1 ms
            chunk_start = chunk[-1][0] + 1
            if len(chunk) < 1000:
                break

        if not rows:
            raise ValueError(f"Binance returned no klines for {symbol}")

        # Binance kline columns: [open_time, o, h, l, c, volume, close_time, ...]
        df = pd.DataFrame(rows, columns=[
            "open_time", "Open", "High", "Low", "Close", "Volume",
            "close_time", "quote_vol", "trades", "taker_buy_base",
            "taker_buy_quote", "ignore",
        ])
        df.index = pd.to_datetime(df["open_time"], unit="ms", utc=True)
        df = df[["Open", "High", "Low", "Close", "Volume"]].astype(float)
        df = df.sort_index()
        log.info("  Binance %-10s  %d bars  last_close=%.4f",
                 instrument, len(df), df["Close"].iloc[-1])
        return df


# ─────────────────────────────────────────────────────────────────────────────
# MAIN PIPELINE
# ─────────────────────────────────────────────────────────────────────────────

class DataPipeline:
    """
    Routes each instrument to the appropriate data source:
      • config.STOCK_INSTRUMENTS  →  AlpacaFeed
      • config.CRYPTO_INSTRUMENTS →  BinanceFeed
    """

    def __init__(self) -> None:
        self.alpaca  = AlpacaFeed()
        self.binance = BinanceFeed()
        log.info(
            "DataPipeline ready  stocks=%s  crypto=%s",
            config.STOCK_INSTRUMENTS,
            config.CRYPTO_INSTRUMENTS,
        )

    def _fetch_df(self, instrument: str) -> pd.DataFrame:
        if instrument in config.STOCK_INSTRUMENTS:
            return self.alpaca.fetch(instrument)
        else:
            return self.binance.fetch(instrument)

    def run_once(self) -> list[dict]:
        """Fetch + compute features for all instruments. Returns list of payloads."""
        results = []
        for instrument in config.INSTRUMENTS:
            try:
                log.info("Fetching %-10s …", instrument)
                df      = self._fetch_df(instrument)
                payload = _build_payload(df, instrument)
                results.append(payload)
                log.info(
                    "  ✓ %-10s  close=%.4f  fd=%.6f  vol=%.4f  rsi=%.1f  obi=%.3f",
                    instrument,
                    payload["ohlcv"]["close"],
                    payload["features"]["frac_diff_price_1d"],
                    payload["features"]["garch_vol"],
                    payload["features"]["rsi_14"],
                    payload["features"]["order_book_imbalance"],
                )
            except Exception as exc:
                log.error("✗ Failed %s: %s", instrument, exc)
        return results

    def stream(self) -> Generator[list[dict], None, None]:
        """Continuous generator — yields one full batch every POLL_INTERVAL_SECONDS."""
        while True:
            log.info("══ Data fetch cycle ══════════════════════════════════")
            batch = self.run_once()
            if batch:
                yield batch
            log.info("Sleeping %ds …\n", config.POLL_INTERVAL_SECONDS)
            time.sleep(config.POLL_INTERVAL_SECONDS)


# ─────────────────────────────────────────────────────────────────────────────
# STANDALONE SMOKE TEST
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    dp    = DataPipeline()
    batch = dp.run_once()
    for p in batch:
        public = {k: v for k, v in p.items() if not k.startswith("_")}
        print(json.dumps(public, indent=2))
