import logging
from typing import Dict, Any, Tuple
from alpaca.trading.client import TradingClient
from alpaca.trading.requests import MarketOrderRequest
from alpaca.trading.enums import OrderSide, TimeInForce
import config

log = logging.getLogger(__name__)

class AlpacaOMS:
    def __init__(self):
        # Default to paper trading
        self.api_key = config.ALPACA_API_KEY
        self.api_secret = config.ALPACA_API_SECRET
        if not self.api_key:
            log.warning("ALPACA_API_KEY is not set. AlpacaOMS orders will fail.")
            self.client = None
        else:
            self.client = TradingClient(self.api_key, self.api_secret, paper=True)

    def get_account_state(self) -> Dict[str, Any]:
        if not self.client: return {}
        try:
            acct = self.client.get_account()
            return {
                "equity": float(acct.equity),
                "cash": float(acct.cash),
                "buying_power": float(acct.buying_power)
            }
        except Exception as e:
            log.error(f"Failed to get Alpaca account state: {e}")
            return {}

    def get_portfolio_exposures(self) -> Tuple[float, Dict[str, float]]:
        if not self.client: return 0.0, {}
        try:
            positions = self.client.get_all_positions()
            total_exp = 0.0
            instr_exp = {}
            for pos in positions:
                market_value = float(pos.market_value)
                instr_exp[pos.symbol] = market_value
                total_exp += abs(market_value)
            return total_exp, instr_exp
        except Exception as e:
            log.error(f"Failed to get Alpaca positions: {e}")
            return 0.0, {}

    def submit_order(self, evaluated_order: Dict[str, Any], current_price: float, obi_rho: float = 0.0) -> Dict[str, Any]:
        if not self.client:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = "Alpaca client not configured"
            return evaluated_order

        symbol = evaluated_order.get("instrument", "")
        qty = abs(evaluated_order.get("qty", 0.0))
        direction = evaluated_order.get("direction", 1)
        side = OrderSide.BUY if direction > 0 else OrderSide.SELL

        if qty <= 0:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = "Qty is zero"
            return evaluated_order

        try:
            req = MarketOrderRequest(
                symbol=symbol,
                qty=qty,
                side=side,
                time_in_force=TimeInForce.GTC
            )
            order = self.client.submit_order(order_data=req)
            evaluated_order["oms_state"] = "SUBMITTED"
            evaluated_order["oms_detail"] = f"Alpaca Order ID: {order.id}"
            evaluated_order["alpaca_order_id"] = str(order.id)
        except Exception as e:
            log.error(f"Failed to submit Alpaca order for {symbol}: {e}")
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = str(e)
            
        return evaluated_order

    def update_prices(self, current_prices: Dict[str, float], atr_values: Dict[str, float]) -> list:
        return []
