"""
execution/simulated_oms.py — Local Simulated Futures OMS

Provides a pure local execution engine with leverage for paper trading.
Tracks P&L, positions, ATR trailing stops, scaled profit taking, and TWAP orders.
"""

from __future__ import annotations
import os
import json
import uuid
import time
import logging
import threading
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

log = logging.getLogger(__name__)

_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "simulated_account.json")
_lock = threading.Lock()

class SimulatedFuturesOMS:
    def __init__(self):
        self._init_state()

    def _init_state(self):
        """Initialize local account state."""
        if not os.path.exists(_STATE_FILE):
            default_state = {
                "equity": 1000.0,
                "realized_pl": 0.0,
                "positions": {}
            }
            self._write_state(default_state)

    def _read_state(self) -> dict:
        with _lock:
            try:
                with open(_STATE_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return {"equity": 1000.0, "realized_pl": 0.0, "positions": {}}

    def _write_state(self, state: dict):
        with _lock:
            with open(_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)

    def update_prices(self, current_prices: dict[str, float], atr_values: dict[str, float] = None):
        """
        Updates mark-to-market prices and evaluates ATR trailing stops & scaled profit targets.
        """
        state = self._read_state()
        changed = False
        atr_values = atr_values or {}
        
        orders_to_execute = []

        for symbol, pos in list(state["positions"].items()):
            if symbol in current_prices:
                current = current_prices[symbol]
                pos["current_price"] = current
                
                qty = pos["qty"]
                entry = pos["entry_price"]
                atr = atr_values.get(symbol, current * 0.015)
                
                if "initial_qty" not in pos:
                    pos["initial_qty"] = qty
                
                # ATR Trailing Stop calculation (k = 2.0)
                k_atr = 2.0 * atr
                if qty > 0: # LONG
                    trailing_stop = max(pos.get("atr_trailing_stop", entry - k_atr), current - k_atr)
                    pos["atr_trailing_stop"] = trailing_stop
                    
                    # Stop Trigger
                    if current <= trailing_stop:
                        log.info(f"[OMS] ATR Trailing Stop Triggered for LONG {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "ATR_TRAILING_STOP", 1.0))
                        
                    # TP1 (+1 ATR)
                    elif current >= entry + atr and not pos.get("tp1_hit"):
                        pos["tp1_hit"] = True
                        log.info(f"[OMS] TP1 (+1 ATR) Triggered for LONG {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "TP1_+1_SIGMA", 0.40))
                        
                    # TP2 (+2 ATR)
                    elif current >= entry + 2 * atr and not pos.get("tp2_hit"):
                        pos["tp2_hit"] = True
                        log.info(f"[OMS] TP2 (+2 ATR) Triggered for LONG {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "TP2_+2_SIGMA", 0.30))
                        
                elif qty < 0: # SHORT
                    trailing_stop = min(pos.get("atr_trailing_stop", entry + k_atr), current + k_atr)
                    pos["atr_trailing_stop"] = trailing_stop
                    
                    # Stop Trigger
                    if current >= trailing_stop:
                        log.info(f"[OMS] ATR Trailing Stop Triggered for SHORT {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "ATR_TRAILING_STOP", 1.0))
                        
                    # TP1 (+1 ATR)
                    elif current <= entry - atr and not pos.get("tp1_hit"):
                        pos["tp1_hit"] = True
                        log.info(f"[OMS] TP1 (+1 ATR) Triggered for SHORT {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "TP1_+1_SIGMA", 0.40))
                        
                    # TP2 (+2 ATR)
                    elif current <= entry - 2 * atr and not pos.get("tp2_hit"):
                        pos["tp2_hit"] = True
                        log.info(f"[OMS] TP2 (+2 ATR) Triggered for SHORT {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "TP2_+2_SIGMA", 0.30))
                
                # Unrealized PnL
                unrealized_pl = (current - entry) * qty
                pos["unrealized_pl"] = unrealized_pl
                
                notional_entry = abs(qty) * entry
                if notional_entry > 0:
                    pos["unrealized_plpc"] = unrealized_pl / notional_entry
                else:
                    pos["unrealized_plpc"] = 0.0
                    
                changed = True

        # Close positions triggered by stops or TP targets
        exits_to_log = []
        for symbol, exit_price, reason, pct in orders_to_execute:
            pos = state["positions"].get(symbol)
            if pos:
                initial_qty = pos.get("initial_qty", pos["qty"])
                close_qty = initial_qty * pct
                
                # Cannot close more than what we currently hold
                if abs(close_qty) > abs(pos["qty"]):
                    close_qty = abs(pos["qty"])
                    
                entry = pos["entry_price"]
                realized_pnl = (exit_price - entry) * abs(close_qty) * (1 if pos["qty"] > 0 else -1)
                
                state["equity"] += realized_pnl
                state["realized_pl"] += realized_pnl
                
                sign = -1 if pos["qty"] > 0 else 1 # Opposite of position
                
                if abs(pos["qty"]) <= abs(close_qty) + 1e-6:
                    del state["positions"][symbol]
                    log.info(f"[OMS] Closed ALL {symbol} ({reason}) Realized PnL: ${realized_pnl:.2f}")
                else:
                    pos["qty"] += sign * abs(close_qty)
                    log.info(f"[OMS] Partial Close {pct*100}% {symbol} ({reason}) Realized PnL: ${realized_pnl:.2f}")
                
                changed = True
                
                # Create execution record for UI and Quota
                exit_exec = {
                    "order_id": "sim_exit_" + uuid.uuid4().hex[:8],
                    "instrument": symbol,
                    "action": "SELL" if sign < 0 else "BUY",
                    "qty": abs(close_qty),
                    "price": exit_price,
                    "oms_state": "FILLED",
                    "realized_pnl": realized_pnl,
                    "reason": reason,
                    "timestamp": time.time()
                }
                exits_to_log.append(exit_exec)

        if changed:
            self._write_state(state)
            
        if exits_to_log:
            self._log_executions(exits_to_log)
            
        return exits_to_log

    def _log_executions(self, execs: list):
        exec_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "execution_store.json")
        with _lock:
            try:
                if os.path.exists(exec_file):
                    with open(exec_file, "r") as f:
                        data = json.load(f)
                else:
                    data = []
            except Exception:
                data = []
            data.extend(execs)
            with open(exec_file, "w") as f:
                json.dump(data, f, indent=2)

    def get_account_state(self) -> dict:
        state = self._read_state()
        total_unrealized_pl = sum(p.get("unrealized_pl", 0.0) for p in state["positions"].values())
        equity = state["equity"] + total_unrealized_pl
        
        total_notional_exposure = sum(abs(p["qty"]) * p.get("current_price", p["entry_price"]) for p in state["positions"].values())
        gross_buying_power = equity * config.FUTURES_LEVERAGE
        available_buying_power = gross_buying_power - total_notional_exposure
        
        return {
            "equity": equity,
            "gross_buying_power": gross_buying_power,
            "buying_power": max(0.0, available_buying_power),
            "cash": state["equity"]
        }

    def get_portfolio_exposures(self) -> tuple[float, dict[str, dict]]:
        state = self._read_state()
        acc = self.get_account_state()
        equity = acc["equity"]
        
        if equity <= 0:
            return 0.0, {}
            
        instrument_data = {}
        total_exposure_val = 0.0
        gross_buying_power = acc["gross_buying_power"]
        
        for symbol, pos in state["positions"].items():
            current_price = pos.get("current_price", pos["entry_price"])
            qty = pos["qty"]
            market_val = abs(qty) * current_price
            total_exposure_val += market_val
            
            instrument_data[symbol] = {
                "exposure_pct": market_val / gross_buying_power if gross_buying_power > 0 else 0.0,
                "unrealized_plpc": pos.get("unrealized_plpc", 0.0)
            }
            
        total_exposure_pct = total_exposure_val / gross_buying_power if gross_buying_power > 0 else 0.0
        return total_exposure_pct, instrument_data

    def submit_order(self, evaluated_order: dict, current_price: float, obi_rho: float = 0.5) -> dict:
        """
        Executes order with LOB Imbalance threshold filter (rho > 0.3 for BUY, rho < -0.3 for SELL).
        """
        if evaluated_order.get("risk_state") != "APPROVED":
            evaluated_order["oms_state"] = "SKIPPED_BY_RISK"
            return evaluated_order
            
        action = evaluated_order["action"] # BUY or SELL
        
        # Microstructure Entry Check: LOB Imbalance rho > 0.3 (buys) or < -0.3 (sells)
        if action == "BUY" and obi_rho < 0.3 and not evaluated_order.get("is_take_profit"):
            evaluated_order["oms_state"] = "REJECTED_LOB_IMBALANCE"
            evaluated_order["oms_detail"] = f"LOB Imbalance rho ({obi_rho:.2f}) < 0.3 buy threshold."
            return evaluated_order
        elif action == "SELL" and obi_rho > -0.3 and not evaluated_order.get("is_take_profit"):
            evaluated_order["oms_state"] = "REJECTED_LOB_IMBALANCE"
            evaluated_order["oms_detail"] = f"LOB Imbalance rho ({obi_rho:.2f}) > -0.3 sell threshold."
            return evaluated_order

        symbol = evaluated_order["instrument"]
        alloc_pct = evaluated_order["portfolio_allocation_pct"]
        atr = evaluated_order.get("atr", current_price * 0.015)
        
        state = self._read_state()
        acc = self.get_account_state()
        equity = acc["equity"]
        
        if current_price <= 0:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = "Invalid price."
            return evaluated_order
            
        is_crypto = symbol in ["BTC-USD", "ETH-USD"]
        
        if not is_crypto:
            # US Futures: $100 Risk Cap Sizing
            risk_per_contract = atr * 10.0
            if risk_per_contract <= 0:
                evaluated_order["oms_state"] = "FAILED"
                return evaluated_order
                
            contracts = int(100.0 // risk_per_contract)
            if contracts < 1:
                evaluated_order["oms_state"] = "REJECTED_RISK_CAP"
                evaluated_order["oms_detail"] = f"1-contract risk (${risk_per_contract:.2f}) > $100 max allowance."
                return evaluated_order
                
            target_qty_abs = contracts * 10.0
            notional_value = target_qty_abs * current_price
        else:
            # Crypto: Half-Kelly
            notional_value = equity * alloc_pct * config.FUTURES_LEVERAGE
            target_qty_abs = notional_value / current_price
            
        order_qty = target_qty_abs if action == "BUY" else -target_qty_abs
        
        pos = state["positions"].get(symbol)
        
        if pos:
            old_qty = pos["qty"]
            old_entry = pos["entry_price"]
            
            if (old_qty > 0 and order_qty < 0) or (old_qty < 0 and order_qty > 0):
                closing_qty = min(abs(old_qty), abs(order_qty))
                realized_pnl = (current_price - old_entry) * closing_qty * (1 if old_qty > 0 else -1)
                state["equity"] += realized_pnl
                state["realized_pl"] += realized_pnl
            
            new_qty = old_qty + order_qty
            if (old_qty > 0 and order_qty > 0) or (old_qty < 0 and order_qty < 0):
                new_entry = ((abs(old_qty) * old_entry) + (abs(order_qty) * current_price)) / abs(new_qty)
            elif abs(new_qty) < 0.0001:
                new_entry = 0.0
                new_qty = 0.0
            else:
                new_entry = current_price

            if new_qty == 0:
                del state["positions"][symbol]
            else:
                pos["qty"] = new_qty
                pos["entry_price"] = new_entry
                pos["current_price"] = current_price
                
        else:
            state["positions"][symbol] = {
                "qty": order_qty,
                "entry_price": current_price,
                "current_price": current_price,
                "atr_trailing_stop": current_price - (0.02 * current_price) if order_qty > 0 else current_price + (0.02 * current_price),
                "unrealized_pl": 0.0,
                "unrealized_plpc": 0.0
            }
            
        self._write_state(state)
        
        evaluated_order["oms_state"] = "SUBMITTED"
        evaluated_order["alpaca_order_id"] = "sim_" + uuid.uuid4().hex[:8]
        evaluated_order["notional_value"] = notional_value
        return evaluated_order
