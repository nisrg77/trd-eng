"""
strategies/crypto — Crypto Perpetuals Strategy Plugins
"""
from strategies.crypto.binh_cluc import BinhClucStrategy
from strategies.crypto.nfi_strategy import NFIStrategy
from strategies.crypto.funding_rate_arb import FundingRateArbStrategy
from strategies.crypto.freqtrade_adapter import FreqtradeAdapter

__all__ = [
    "BinhClucStrategy",
    "NFIStrategy",
    "FundingRateArbStrategy",
    "FreqtradeAdapter"
]
