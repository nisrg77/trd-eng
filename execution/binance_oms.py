import logging
import requests
import time
import hmac
import hashlib
from typing import Dict, Any, Tuple
import os

log = logging.getLogger(__name__)

class BinanceOMS:
    BASE_URL = "https://testnet.binancefuture.com"
    
    def __init__(self):
        self.api_key = os.environ.get("BINANCE_API_KEY", "")
        self.api_secret = os.environ.get("BINANCE_API_SECRET", "")
        self.private_key_content = os.environ.get("BINANCE_PRIVATE_KEY", "")
        
        if not self.api_key:
            log.warning("BINANCE_API_KEY is not set. BinanceOMS will fail.")
            
        self.private_key = None
        if self.private_key_content:
            try:
                from cryptography.hazmat.primitives import serialization
                # Handle literal \n if passed directly from env
                content = self.private_key_content.replace('\\n', '\n')
                self.private_key = serialization.load_pem_private_key(
                    content.encode('utf-8'),
                    password=None
                )
                log.info("Loaded Ed25519 Private Key for Binance API.")
            except Exception as e:
                log.error(f"Failed to load Ed25519 private key: {e}")

        self.session = requests.Session()
        self.session.headers.update({
            "X-MBX-APIKEY": self.api_key
        })

    def _sign(self, params: dict) -> str:
        query_string = "&".join([f"{k}={v}" for k, v in params.items()])
        if self.private_key:
            import base64
            signature_bytes = self.private_key.sign(query_string.encode('utf-8'))
            return base64.b64encode(signature_bytes).decode('utf-8')
        else:
            signature = hmac.new(
                self.api_secret.encode('utf-8'),
                query_string.encode('utf-8'),
                hashlib.sha256
            ).hexdigest()
            return signature

    def get_account_state(self) -> Dict[str, Any]:
        if not self.api_key: return {}
        try:
            params = {"timestamp": int(time.time() * 1000), "recvWindow": 60000}
            params["signature"] = self._sign(params)
            r = self.session.get(f"{self.BASE_URL}/fapi/v2/account", params=params)
            r.raise_for_status()
            data = r.json()
            return {
                "equity": float(data.get("totalWalletBalance", 0.0)),
                "cash": float(data.get("availableBalance", 0.0)),
                "buying_power": float(data.get("maxWithdrawAmount", 0.0))
            }
        except Exception as e:
            log.error(f"Failed to get Binance account state: {e}")
            return {}

    def get_portfolio_exposures(self) -> Tuple[float, Dict[str, float]]:
        if not self.api_key: return 0.0, {}
        try:
            params = {"timestamp": int(time.time() * 1000), "recvWindow": 60000}
            params["signature"] = self._sign(params)
            r = self.session.get(f"{self.BASE_URL}/fapi/v2/positionRisk", params=params)
            r.raise_for_status()
            positions = r.json()
            total_exp = 0.0
            instr_exp = {}
            for pos in positions:
                amt = float(pos["positionAmt"])
                if amt != 0:
                    symbol = pos["symbol"].replace("USDT", "-USD")
                    notional = float(pos["notional"])
                    instr_exp[symbol] = notional
                    total_exp += abs(notional)
            return total_exp, instr_exp
        except Exception as e:
            log.error(f"Failed to get Binance positions: {e}")
            return 0.0, {}

    def submit_order(self, evaluated_order: Dict[str, Any], current_price: float, obi_rho: float = 0.0) -> Dict[str, Any]:
        if not self.api_key:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = "Binance client not configured"
            return evaluated_order

        symbol = evaluated_order.get("instrument", "").replace("-USD", "USDT")
        
        # NOTE: Quantities on Binance Futures might need precision formatting
        # For simplicity, sending raw float for now, but in production we'd use exchange info lot sizes
        qty = abs(evaluated_order.get("qty", 0.0))
        direction = evaluated_order.get("direction", 1)
        side = "BUY" if direction > 0 else "SELL"

        if qty <= 0:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = "Qty is zero"
            return evaluated_order

        try:
            params = {
                "symbol": symbol,
                "side": side,
                "type": "MARKET",
                "quantity": round(qty, 3), # Rough rounding, ideally dynamic
                "timestamp": int(time.time() * 1000),
                "recvWindow": 60000
            }
            params["signature"] = self._sign(params)
            r = self.session.post(f"{self.BASE_URL}/fapi/v1/order", params=params)
            r.raise_for_status()
            order = r.json()
            evaluated_order["oms_state"] = "SUBMITTED"
            evaluated_order["oms_detail"] = f"Binance Order ID: {order['orderId']}"
            evaluated_order["binance_order_id"] = str(order['orderId'])
        except Exception as e:
            log.error(f"Failed to submit Binance order for {symbol}: {e}")
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = str(e)
            
        return evaluated_order

    def update_prices(self, current_prices: Dict[str, float], atr_values: Dict[str, float]) -> list:
        return []
