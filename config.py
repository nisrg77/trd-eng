"""
config.py — TEDENG Central Parameters
All layers import from here. Sensitive values are loaded from .env
"""

import os
from pathlib import Path

# Load .env if present (no dependency on python-dotenv — manual parse)
_ENV_FILE = Path(__file__).parent / ".env"
if _ENV_FILE.exists():
    for _line in _ENV_FILE.read_text().splitlines():
        _line = _line.strip()
        if _line and not _line.startswith("#") and "=" in _line:
            _k, _v = _line.split("=", 1)
            os.environ.setdefault(_k.strip(), _v.strip())

# ─────────────────────────────────────────────────────────────────────────────
# INSTRUMENTS
# ─────────────────────────────────────────────────────────────────────────────
# Crypto instruments  (fetched via Binance or yfinance)
CRYPTO_INSTRUMENTS: list[str] = ["BTC-USD", "ETH-USD"]

# US Stock instruments (fetched via Alpaca)
STOCK_INSTRUMENTS: list[str] = ["AAPL", "SPY"]

# Combined list used everywhere else
INSTRUMENTS: list[str] = CRYPTO_INSTRUMENTS + STOCK_INSTRUMENTS

# ─────────────────────────────────────────────────────────────────────────────
# ALPACA  (US Stocks — Paper Trading)
# ─────────────────────────────────────────────────────────────────────────────
ALPACA_API_KEY:    str = os.environ.get("ALPACA_API_KEY", "")
ALPACA_API_SECRET: str = os.environ.get("ALPACA_API_SECRET", "")
ALPACA_BASE_URL:   str = os.environ.get("ALPACA_BASE_URL", "https://paper-api.alpaca.markets/v2")
ALPACA_DATA_URL:   str = os.environ.get("ALPACA_DATA_URL", "https://data.alpaca.markets/v2")

# ─────────────────────────────────────────────────────────────────────────────
# BINANCE  (Crypto — public market data, no key needed for signals)
# ─────────────────────────────────────────────────────────────────────────────
BINANCE_BASE_URL: str = os.environ.get("BINANCE_BASE_URL", "https://api.binance.com")

# ─────────────────────────────────────────────────────────────────────────────
# DATA PIPELINE  (DP)
# ─────────────────────────────────────────────────────────────────────────────
LOOKBACK_DAYS: int = 365          # history window for feature calculation
DATA_INTERVAL: str = "1Day"      # Alpaca timeframe: 1Min, 5Min, 1Hour, 1Day
POLL_INTERVAL_SECONDS: int = 3   # Reduced to 3 seconds for REAL-TIME Mark-To-Market updates

FRAC_DIFF_D: float = 0.4         # fractional-differentiation order (0 < d < 1)
VOL_WINDOW: int = 5              # rolling window (bars) for GARCH-proxy vol
RSI_PERIOD: int = 14             # RSI look-back

# ─────────────────────────────────────────────────────────────────────────────
# FEATURE PRE-PROCESSOR  (PP)
# ─────────────────────────────────────────────────────────────────────────────
ZSCORE_WINDOW: int = 60          # rolling window for Z-score normalisation
IMPUTE_STRATEGY: str = "ffill"   # "ffill" | "mean"

# ─────────────────────────────────────────────────────────────────────────────
# ENSEMBLE MODELS
# ─────────────────────────────────────────────────────────────────────────────
TRAINING_LOOKBACK_BARS: int = 252
WALK_FORWARD_RETRAIN_EVERY: int = 50
MODEL_WEIGHTS_DIR: str = "model_weights"

# Ridge
RIDGE_ALPHA: float = 1.0

# XGBoost
XGB_N_ESTIMATORS: int = 100
XGB_MAX_DEPTH: int = 4
XGB_LEARNING_RATE: float = 0.05

# LSTM
LSTM_SEQ_LEN: int = 30
LSTM_UNITS: int = 64
LSTM_DROPOUT: float = 0.2
LSTM_EPOCHS: int = 20
LSTM_BATCH_SIZE: int = 32

# ─────────────────────────────────────────────────────────────────────────────
# META-AGGREGATOR  (MA)
# ─────────────────────────────────────────────────────────────────────────────
REGIME_VOL_THRESHOLD_HIGH: float = 0.020
REGIME_VOL_THRESHOLD_LOW: float  = 0.008

REGIME_WEIGHTS: dict = {
    "low_volatility":  {"ridge": 0.50, "xgb": 0.30, "lstm": 0.20},
    "trending":        {"ridge": 0.20, "xgb": 0.45, "lstm": 0.35},
    "high_volatility": {"ridge": 0.10, "xgb": 0.30, "lstm": 0.60},
}

# ─────────────────────────────────────────────────────────────────────────────
# MIDDLEWARE — REDIS  (MB)
# ─────────────────────────────────────────────────────────────────────────────
REDIS_HOST: str = os.environ.get("REDIS_HOST", "localhost")
REDIS_PORT: int = int(os.environ.get("REDIS_PORT", "6379"))
REDIS_DB: int = 0

REDIS_CHANNEL_FEATURES: str = "tedeng:features"
REDIS_CHANNEL_SIGNALS:  str = "tedeng:signals"

# ─────────────────────────────────────────────────────────────────────────────
# EXECUTION ENGINE  (EE) & RISK GUARD (RG) PROFILES
# ─────────────────────────────────────────────────────────────────────────────
# The dashboard allows switching between these profiles dynamically.
RISK_PROFILES: dict = {
    "Conservative": {
        "KELLY_FRACTION": 0.25,
        "MAX_POSITION_SIZE_PCT": 0.10,
        "MAX_DRAWDOWN_PCT": 0.05,
        "MAX_EXPOSURE_PCT": 0.50,
        "CONCENTRATION_LIMIT_PCT": 0.15,
        "PARTIAL_TP_THRESHOLD_PCT": 0.05, # Take profit at +5% gain
        "PARTIAL_TP_SELL_PCT": 0.50,      # Sell 50% of the position
    },
    "Balanced": {
        "KELLY_FRACTION": 0.50,
        "MAX_POSITION_SIZE_PCT": 0.20,
        "MAX_DRAWDOWN_PCT": 0.15,
        "MAX_EXPOSURE_PCT": 1.20,
        "CONCENTRATION_LIMIT_PCT": 0.40,
        "PARTIAL_TP_THRESHOLD_PCT": 0.10, # Take profit at +10% gain
        "PARTIAL_TP_SELL_PCT": 0.50,      # Sell 50% of the position
    },
    "Aggressive": {
        "KELLY_FRACTION": 1.00,
        "MAX_POSITION_SIZE_PCT": 0.40,
        "MAX_DRAWDOWN_PCT": 0.30,
        "MAX_EXPOSURE_PCT": 1.50, # Allows margin
        "CONCENTRATION_LIMIT_PCT": 0.50,
        "PARTIAL_TP_THRESHOLD_PCT": 0.20, # Take profit at +20% gain
        "PARTIAL_TP_SELL_PCT": 0.25,      # Sell only 25% of the position to let more run
    }
}

ACTIVE_RISK_PROFILE: str = "Balanced" # Default profile

MIN_CONFIDENCE_THRESHOLD: float = 0.20 # Lowered to allow bot to immediately execute trades
PAPER_TRADING_ENABLED: bool = True     # Re-enable bot OMS execution
USE_SIMULATED_FUTURES: bool = True     # Bypass Alpaca and use local simulated futures engine
FUTURES_LEVERAGE: float = float(os.environ.get("MAX_LEVERAGE", "10.0"))
INITIAL_CAPITAL: float = float(os.environ.get("INITIAL_CAPITAL", "1000.0"))

# ─────────────────────────────────────────────────────────────────────────────
# DASHBOARD
# ─────────────────────────────────────────────────────────────────────────────
DASHBOARD_REFRESH_SECONDS: int = 10
SIGNAL_HISTORY_MAX: int = 200
