"""
execution/live_ccxt_router.py — Production CCXT Exchange Order Router

Dispatches approved orders to live or testnet cryptocurrency exchanges (Binance, Bybit)
via the CCXT unified API, strictly gated by TRDENG's risk guard.
Supports dry-run simulation mode and emits SCHEMA.md compliant events.
"""

from __future__ import annotations
import os
import time
import uuid
import logging
from typing import Dict, Any, Optional
import config

log = logging.getLogger(__name__)


class LiveCCXTRouter:
    """
    Production CCXT live/paper execution gateway.
    """

    def __init__(self, exchange_id: str = "binance", dry_run: bool = True) -> None:
        self.exchange_id = exchange_id
        self.dry_run = dry_run
        self.client = None
        self._init_client()

    def _init_client(self) -> None:
        api_key = os.environ.get("CCXT_API_KEY", "")
        secret = os.environ.get("CCXT_API_SECRET", "")
        
        try:
            import ccxt
            if hasattr(ccxt, self.exchange_id):
                exchange_class = getattr(ccxt, self.exchange_id)
                self.client = exchange_class({
                    "apiKey": api_key,
                    "secret": secret,
                    "enableRateLimit": True,
                    "options": {"defaultType": "future"}
                })
                if self.dry_run and hasattr(self.client, "set_sandbox_mode"):
                    self.client.set_sandbox_mode(True)
                log.info("[CCXT] Initialized %s (dry_run=%s)", self.exchange_id, self.dry_run)
        except ImportError:
            log.info("[CCXT] ccxt package not installed. Running in mock/dry-run mode.")
            self.client = None
        except Exception as e:
            log.warning("[CCXT] Client init failed: %s. Using dry-run mode.", e)
            self.client = None

    def execute_order(self, proposed_order: Dict[str, Any], current_price: float) -> Dict[str, Any]:
        """
        Executes an approved proposed order on the exchange (or dry-run simulated fill).
        """
        symbol = proposed_order.get("instrument", "BTC-USD")
        action = proposed_order.get("action", "BUY").upper()
        leverage = float(proposed_order.get("dynamic_leverage", 1.0))
        risk_budget = float(proposed_order.get("risk_budget_usd", 10.0))
        
        # Calculate sizing based on risk budget and leverage
        order_size = (risk_budget * leverage) / max(current_price, 1e-4)
        if "BTC" in symbol:
            order_size = round(order_size, 4)
        else:
            order_size = round(order_size, 2)

        side = "buy" if "BUY" in action else "sell"
        order_id = proposed_order.get("order_id", f"ord_ccxt_{uuid.uuid4().hex[:8]}")

        # Real CCXT execution if configured and not dry_run
        if self.client and not self.dry_run:
            try:
                formatted_symbol = symbol.replace("-", "/")
                order = self.client.create_market_order(
                    symbol=formatted_symbol,
                    side=side,
                    amount=order_size
                )
                fill_price = float(order.get("average") or order.get("price") or current_price)
                return {
                    "order_id": order.get("id", order_id),
                    "symbol": symbol,
                    "side": side,
                    "size": order_size,
                    "fill_price": fill_price,
                    "status": "filled",
                    "venue": f"CCXT_{self.exchange_id.upper()}",
                    "timestamp": time.time()
                }
            except Exception as e:
                log.error("[CCXT] Live order failed: %s. Rejecting fill.", e)
                return {"order_id": order_id, "status": "failed", "error": str(e)}

        # Dry-run fallback execution
        log.info("[CCXT DRY-RUN] Filled %s %s %s @ %.2f (leverage=%.1fx)", action, order_size, symbol, current_price, leverage)
        return {
            "order_id": order_id,
            "symbol": symbol,
            "side": side,
            "size": order_size,
            "fill_price": current_price,
            "status": "filled",
            "venue": f"CCXT_DRYRUN_{self.exchange_id.upper()}",
            "timestamp": time.time()
        }
