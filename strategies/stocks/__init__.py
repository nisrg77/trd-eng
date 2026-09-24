"""
strategies/stocks — US Equities and Futures Strategy Plugins
"""
from strategies.stocks.orb_breakout import ORBBreakoutStrategy
from strategies.stocks.vpoc_reversion import VPOCReversionStrategy

__all__ = [
    "ORBBreakoutStrategy",
    "VPOCReversionStrategy"
]
