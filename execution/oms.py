"""
execution/oms.py — Order Management System (OMS)

Connects to Alpaca Paper Trading API to submit approved orders,
fetch active positions, and calculate current portfolio exposures.
"""

from __future__ import annotations
import logging
import requests
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger(__name__)

class AlpacaOMS:
    def __init__(self):
        if not config.ALPACA_API_KEY:
            log.warning("ALPACA_API_KEY missing - paper trading will fail.")
            
        self.headers = {
            "APCA-API-KEY-ID": config.ALPACA_API_KEY,
            "APCA-API-SECRET-KEY": config.ALPACA_API_SECRET,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self.base_url = config.ALPACA_BASE_URL # https://paper-api.alpaca.markets/v2
        
    def _map_symbol(self, instrument: str) -> str:
        """Map generic TEDENG instruments to Alpaca symbols."""
        if instrument == "BTC-USD":
            return "BTC/USD"
        if instrument == "ETH-USD":
            return "ETH/USD"
        return instrument # e.g. AAPL, SPY

    def get_account_state(self) -> dict:
        """Fetch total equity and buying power from Alpaca."""
        url = f"{self.base_url}/account"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            return {
                "equity": float(data.get("equity", 0.0)),
                "buying_power": float(data.get("buying_power", 0.0)),
            }
        except Exception as e:
            log.error("Failed to fetch Alpaca account state: %s", e)
            return {"equity": 100000.0, "buying_power": 100000.0} # Fallback for local testing

    def get_portfolio_exposures(self) -> tuple[float, dict[str, dict]]:
        """
        Returns (total_exposure_pct, dict_of_instrument_data).
        Fetches active positions and compares to total equity.
        instrument_data contains 'exposure_pct' and 'unrealized_plpc'.
        """
        account = self.get_account_state()
        equity = account["equity"]
        
        url = f"{self.base_url}/positions"
        try:
            resp = requests.get(url, headers=self.headers, timeout=10)
            resp.raise_for_status()
            positions = resp.json()
        except Exception as e:
            log.error("Failed to fetch Alpaca positions: %s", e)
            return 0.0, {}
            
        if equity <= 0:
            return 0.0, {}
            
        instrument_data = {}
        total_exposure_val = 0.0
        
        for p in positions:
            symbol = p.get("symbol")
            # Map back to TEDENG instrument name
            if symbol == "BTC/USD": instr = "BTC-USD"
            elif symbol == "ETH/USD": instr = "ETH-USD"
            else: instr = symbol
            
            market_val = abs(float(p.get("market_value", 0.0)))
            total_exposure_val += market_val
            
            instrument_data[instr] = {
                "exposure_pct": market_val / equity,
                "unrealized_plpc": float(p.get("unrealized_plpc", 0.0))
            }
            
        total_exposure_pct = total_exposure_val / equity
        return total_exposure_pct, instrument_data

    def submit_order(self, evaluated_order: dict, current_price: float = 0.0) -> dict:
        """
        Translates a TEDENG order to an Alpaca Market Order.
        Supports fractional shares via notional value.
        If PAPER_TRADING_ENABLED is False, skips actual API submission.
        """
        if evaluated_order.get("risk_state") != "APPROVED":
            evaluated_order["oms_state"] = "SKIPPED_BY_RISK"
            return evaluated_order
            
        if not config.PAPER_TRADING_ENABLED:
            evaluated_order["oms_state"] = "SKIPPED_PAPER_TRADING_DISABLED"
            evaluated_order["oms_detail"] = "Paper trading is disabled in config."
            evaluated_order["alpaca_order_id"] = "simulated_order_" + str(uuid.uuid4())[:8]
            return evaluated_order

        # Market Session Check
        from execution.market_session import is_market_session_open
        is_open, session_reason, _ = is_market_session_open(evaluated_order.get("instrument", ""))
        if not is_open and not evaluated_order.get("is_take_profit"):
            evaluated_order["oms_state"] = "REJECTED_MARKET_CLOSED"
            evaluated_order["oms_detail"] = session_reason
            return evaluated_order
            
        account = self.get_account_state()
        equity = account["equity"]
        alloc_pct = evaluated_order["portfolio_allocation_pct"]
        notional_value = equity * alloc_pct
        
        if notional_value < 1.0:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = f"Notional value ${notional_value:.2f} is too low."
            return evaluated_order

        symbol = self._map_symbol(evaluated_order["instrument"])
        side = "buy" if evaluated_order["action"] == "BUY" else "sell"
        
        # Build Alpaca payload (using fractional notional orders)
        payload = {
            "symbol": symbol,
            "notional": round(notional_value, 2),
            "side": side,
            "type": "market",
            "time_in_force": "day" if side == "buy" else "gtc",
            "client_order_id": evaluated_order["order_id"][:48] # Max 48 chars
        }
        
        now_ts = time.time()
        qty_est = (notional_value / current_price) if current_price > 0 else 1.0
        evaluated_order["timestamp_executed"] = now_ts
        evaluated_order["price"] = current_price
        evaluated_order["qty"] = round(qty_est if side == "buy" else -qty_est, 4)
        evaluated_order["quantity"] = round(abs(qty_est), 4)
        evaluated_order["realized_pnl"] = 0.0

        url = f"{self.base_url}/orders"
        try:
            resp = requests.post(url, headers=self.headers, json=payload, timeout=10)
            data = resp.json()
            if resp.status_code in (200, 201):
                evaluated_order["oms_state"] = "SUBMITTED"
                evaluated_order["alpaca_order_id"] = data.get("id")
                evaluated_order["notional_value"] = notional_value
                log.info("OMS submitted order %s for %s: %s", evaluated_order["order_id"], symbol, data.get("status"))
            else:
                evaluated_order["oms_state"] = "FAILED"
                evaluated_order["oms_detail"] = data.get("message", str(data))
                log.error("OMS failed to submit order %s: %s", evaluated_order["order_id"], evaluated_order["oms_detail"])
        except Exception as e:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = str(e)
            log.error("OMS exception submitting order %s: %s", evaluated_order["order_id"], e)
            
        return evaluated_order
