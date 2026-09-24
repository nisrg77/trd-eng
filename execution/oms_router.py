import logging
from typing import Dict, Any, Tuple
from execution.alpaca_oms import AlpacaOMS
from execution.binance_oms import BinanceOMS

log = logging.getLogger(__name__)

class UnifiedOMS:
    """Routes orders and state requests to either Binance or Alpaca based on asset class."""
    def __init__(self):
        self.alpaca = AlpacaOMS()
        self.binance = BinanceOMS()

    def _is_crypto(self, instrument: str) -> bool:
        # Check if instrument ends with -USD and isn't a known stock ticker just in case
        return instrument.endswith("-USD")

    def get_account_state(self) -> Dict[str, Any]:
        alpaca_state = self.alpaca.get_account_state()
        binance_state = self.binance.get_account_state()
        return {
            "equity": alpaca_state.get("equity", 0) + binance_state.get("equity", 0),
            "alpaca_equity": alpaca_state.get("equity", 0),
            "binance_equity": binance_state.get("equity", 0)
        }

    def get_portfolio_exposures(self) -> Tuple[float, Dict[str, float]]:
        alpaca_tot, alpaca_exp = self.alpaca.get_portfolio_exposures()
        binance_tot, binance_exp = self.binance.get_portfolio_exposures()
        
        merged_exp = {**alpaca_exp, **binance_exp}
        return alpaca_tot + binance_tot, merged_exp

    def submit_order(self, evaluated_order: Dict[str, Any], current_price: float, obi_rho: float = 0.0) -> Dict[str, Any]:
        instrument = evaluated_order.get("instrument", "")
        if self._is_crypto(instrument):
            return self.binance.submit_order(evaluated_order, current_price, obi_rho)
        else:
            return self.alpaca.submit_order(evaluated_order, current_price, obi_rho)

    def update_prices(self, current_prices: Dict[str, float], atr_values: Dict[str, float]) -> list:
        # Exits are managed natively on the exchanges or through direct API cancel/replace.
        return []
