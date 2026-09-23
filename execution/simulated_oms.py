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

try:
    from alpha_overlay.vap_cvd import get_vpoc, get_vah_val
    _VAP_AVAILABLE = True
except ImportError:
    _VAP_AVAILABLE = False

    def get_vpoc(symbol):   # type: ignore
        return None

    def get_vah_val(symbol, value_area_pct=None):  # type: ignore
        return None

log = logging.getLogger(__name__)

_STATE_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "simulated_account.json")
_lock = threading.Lock()


def _snap_tp(
    symbol: str,
    atr_target: float,
    entry: float,
    is_long: bool,
) -> float:
    """
    Return the closer of `atr_target` and the nearest VAP structural level
    (VAH for longs, VAL for shorts).  The snap is only applied when:
      • VAP data exists for the symbol.
      • The structural level is strictly between entry and the ATR target
        (i.e. it is a genuinely reachable, tighter barrier).
    Falls back to `atr_target` when VAP data is unavailable or inapplicable.
    """
    levels = get_vah_val(symbol)
    if levels is None:
        return atr_target
    vah, val = levels
    structural = vah if is_long else val
    if is_long:
        # Snap to one-tick below VAH if it is closer to entry than the ATR target
        tick = max(0.01, entry * 0.00025)  # ~0.025% of price as a tick size proxy
        candidate = structural - tick
        if entry < candidate < atr_target:
            return candidate
    else:
        # Snap to one-tick above VAL if it is closer to entry than the ATR target
        tick = max(0.01, entry * 0.00025)
        candidate = structural + tick
        if atr_target < candidate < entry:
            return candidate
    return atr_target


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
        Publishes SCHEMA.md compliant position_update and execution_log events to event_bus.
        """
        from middleware.event_bus import event_bus, to_iso8601

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
                if "trade_id" not in pos:
                    pos["trade_id"] = "trd_" + uuid.uuid4().hex[:8]
                if "opened_at" not in pos:
                    pos["opened_at"] = to_iso8601()
                
                # ATR Trailing Stop calculation (k = 2.0)
                k_atr = 2.0 * atr
                spread = max(0.01, current * 0.0002)
                slippage = max(0.005, current * 0.0001)
                commission = max(1.0, abs(qty) * 0.005)
                friction_buffer = spread + (2.0 * slippage) + (2.0 * commission / max(1.0, abs(qty)))

                if qty > 0: # LONG
                    trailing_stop = max(pos.get("atr_trailing_stop", entry - k_atr), current - k_atr)
                    pos["atr_trailing_stop"] = trailing_stop

                    # Stop Trigger
                    if current <= trailing_stop:
                        log.info(f"[OMS] ATR Trailing Stop Triggered for LONG {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "ATR_TRAILING_STOP", 1.0))

                    # TP1 — snap to VAH if it is a tighter structural target than +1 ATR
                    elif not pos.get("tp1_hit"):
                        tp1_dist = entry + atr + friction_buffer
                        tp1_snap = _snap_tp(symbol, tp1_dist, entry, is_long=True)
                        if current >= tp1_snap:
                            pos["tp1_hit"] = True
                            reason = "TP1_VAP_SNAP" if tp1_snap < tp1_dist else "TP1_+1_SIGMA"
                            log.info(f"[OMS] {reason} Triggered for LONG {symbol} @ {current:.2f} (target={tp1_snap:.2f})")
                            orders_to_execute.append((symbol, current, reason, 0.40))

                    # TP2 — snap to VPOC if it is a tighter structural target than +2 ATR
                    elif not pos.get("tp2_hit"):
                        tp2_dist = entry + 2 * atr + friction_buffer
                        vpoc = get_vpoc(symbol)
                        if vpoc and entry < vpoc < tp2_dist:
                            tick = max(0.01, entry * 0.00025)
                            tp2_snap = vpoc - tick
                        else:
                            tp2_snap = tp2_dist
                        if current >= tp2_snap:
                            pos["tp2_hit"] = True
                            reason = "TP2_VAP_SNAP" if tp2_snap > tp2_dist else "TP2_+2_SIGMA"
                            log.info(f"[OMS] {reason} Triggered for LONG {symbol} @ {current:.2f} (target={tp2_snap:.2f})")
                            orders_to_execute.append((symbol, current, reason, 0.30))
                        
                elif qty < 0: # SHORT
                    trailing_stop = min(pos.get("atr_trailing_stop", entry + k_atr), current + k_atr)
                    pos["atr_trailing_stop"] = trailing_stop

                    # Stop Trigger
                    if current >= trailing_stop:
                        log.info(f"[OMS] ATR Trailing Stop Triggered for SHORT {symbol} @ {current:.2f}")
                        orders_to_execute.append((symbol, current, "ATR_TRAILING_STOP", 1.0))

                    # TP1 — snap to VAL if it is a tighter structural target than -1 ATR
                    elif not pos.get("tp1_hit"):
                        tp1_dist = entry - atr - friction_buffer
                        tp1_snap = _snap_tp(symbol, tp1_dist, entry, is_long=False)
                        if current <= tp1_snap:
                            pos["tp1_hit"] = True
                            reason = "TP1_VAP_SNAP" if tp1_snap > tp1_dist else "TP1_+1_SIGMA"
                            log.info(f"[OMS] {reason} Triggered for SHORT {symbol} @ {current:.2f} (target={tp1_snap:.2f})")
                            orders_to_execute.append((symbol, current, reason, 0.40))

                    # TP2 — snap to VPOC if it is a tighter structural target than -2 ATR
                    elif not pos.get("tp2_hit"):
                        tp2_dist = entry - 2 * atr - friction_buffer
                        vpoc = get_vpoc(symbol)
                        if vpoc and tp2_dist < vpoc < entry:
                            tick = max(0.01, entry * 0.00025)
                            tp2_snap = vpoc + tick
                        else:
                            tp2_snap = tp2_dist
                        if current <= tp2_snap:
                            pos["tp2_hit"] = True
                            reason = "TP2_VAP_SNAP" if tp2_snap > tp2_dist else "TP2_+2_SIGMA"
                            log.info(f"[OMS] {reason} Triggered for SHORT {symbol} @ {current:.2f} (target={tp2_snap:.2f})")
                            orders_to_execute.append((symbol, current, reason, 0.30))

                
                # Pure mark-to-market Unrealized PnL (without un-realized friction pre-deduction)
                side_mult = 1.0 if qty > 0 else -1.0
                unrealized_pl = round((current - entry) * abs(qty) * side_mult, 2)
                pos["unrealized_pl"] = unrealized_pl
                
                notional_entry = abs(qty) * entry
                pos["unrealized_plpc"] = (unrealized_pl / notional_entry) if notional_entry > 0 else 0.0
                changed = True

                # Publish price tick position update
                event_bus.publish_position_update(
                    trade_id=pos["trade_id"],
                    symbol=symbol,
                    side="long" if qty > 0 else "short",
                    size=abs(qty),
                    leverage=pos.get("leverage", getattr(config, "FUTURES_LEVERAGE", 10.0)),
                    entry_price=entry,
                    mark_price=current,
                    status="open",
                    opened_at=pos["opened_at"],
                    unrealized_pnl=unrealized_pl,
                    realized_pnl=pos.get("realized_pnl")
                )

        # Close positions triggered by stops or TP targets
        exits_to_log = []
        for symbol, exit_price, reason, pct in orders_to_execute:
            pos = state["positions"].get(symbol)
            if pos:
                initial_qty = pos.get("initial_qty", pos["qty"])
                close_qty = initial_qty * pct
                
                if abs(close_qty) > abs(pos["qty"]):
                    close_qty = abs(pos["qty"])
                    
                entry = pos["entry_price"]
                spread = max(0.01, exit_price * 0.0002)
                half_spread = spread / 2.0
                slippage = max(0.005, exit_price * 0.0001)
                eff_exit_price = exit_price - half_spread - slippage if pos["qty"] > 0 else exit_price + half_spread + slippage
                commission = max(1.0, abs(close_qty) * 0.005)
                realized_pnl = round(((eff_exit_price - entry) * abs(close_qty) * (1 if pos["qty"] > 0 else -1)) - commission, 2)
                
                state["balance"] = round(state.get("balance", 1000.0) + realized_pnl, 2)
                state["realized_pl"] = round(state.get("realized_pl", 0.0) + realized_pnl, 2)
                pos["realized_pnl"] = round(pos.get("realized_pnl", 0.0) + realized_pnl, 2)
                
                sign = -1 if pos["qty"] > 0 else 1
                closed_at_str = to_iso8601()
                
                is_full_close = abs(pos["qty"]) <= abs(close_qty) + 1e-6
                
                if is_full_close:
                    del state["positions"][symbol]
                    log.info(f"[OMS] Closed ALL {symbol} ({reason}) Realized PnL: ${realized_pnl:.2f}")
                    
                    # Emit position_update with status="closed"
                    event_bus.publish_position_update(
                        trade_id=pos["trade_id"],
                        symbol=symbol,
                        side="long" if pos["qty"] > 0 else "short",
                        size=abs(pos["qty"]),
                        leverage=pos.get("leverage", getattr(config, "FUTURES_LEVERAGE", 10.0)),
                        entry_price=entry,
                        exit_price=eff_exit_price,
                        mark_price=exit_price,
                        status="closed",
                        opened_at=pos["opened_at"],
                        closed_at=closed_at_str,
                        unrealized_pnl=0.0,
                        realized_pnl=pos["realized_pnl"]
                    )
                else:
                    pos["qty"] += sign * abs(close_qty)
                    log.info(f"[OMS] Partial Close {pct*100}% {symbol} ({reason}) Realized PnL: ${realized_pnl:.2f}")
                    
                    # Emit position_update for partial close
                    event_bus.publish_position_update(
                        trade_id=pos["trade_id"],
                        symbol=symbol,
                        side="long" if pos["qty"] > 0 else "short",
                        size=abs(pos["qty"]),
                        leverage=pos.get("leverage", getattr(config, "FUTURES_LEVERAGE", 10.0)),
                        entry_price=entry,
                        mark_price=exit_price,
                        status="open",
                        opened_at=pos["opened_at"],
                        unrealized_pnl=pos.get("unrealized_pl", 0.0),
                        realized_pnl=pos["realized_pnl"]
                    )

                changed = True
                
                # Emit execution_log event
                event_bus.publish_execution_log(
                    level="fill",
                    category="exit_fill",
                    symbol=symbol,
                    message=f"[{reason}] Exit fill {symbol} @ {eff_exit_price:.2f} (Realized PnL: ${realized_pnl:+.2f})",
                    order_id="sim_exit_" + uuid.uuid4().hex[:8]
                )
                
                # Create execution record for store
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

                try:
                    from goals.goal_module import record_trade_result
                    ac = "crypto" if symbol in ["BTC-USD", "ETH-USD"] else "stock"
                    record_trade_result(ac, realized_pnl)
                except Exception as ge:
                    log.warning(f"[OMS] Error recording trade to GoalModule: {ge}")

        if changed:
            tot_unrealized = sum(p.get("unrealized_pl", 0.0) for p in state["positions"].values())
            balance = state.get("balance", 1000.0)
            state["balance"] = round(balance, 2)
            state["unrealized_pl"] = round(tot_unrealized, 2)
            state["equity"] = round(balance + tot_unrealized, 2)
            state["total_pl"] = round(state.get("realized_pl", 0.0) + tot_unrealized, 2)
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
        balance = state.get("balance", 1000.0)
        total_unrealized_pl = sum(p.get("unrealized_pl", 0.0) for p in state["positions"].values())
        realized_pl = state.get("realized_pl", 0.0)
        equity = balance + total_unrealized_pl
        total_pl = realized_pl + total_unrealized_pl
        
        total_notional_exposure = sum(abs(p["qty"]) * p.get("current_price", p["entry_price"]) for p in state["positions"].values())
        effective_leverage = (total_notional_exposure / equity) if equity > 0 else 0.0
        
        leverage_factor = getattr(config, "FUTURES_LEVERAGE", 10.0)
        gross_buying_power = equity * leverage_factor
        margin_used = total_notional_exposure / leverage_factor
        free_margin = max(0.0, equity - margin_used)
        available_buying_power = free_margin * leverage_factor
        margin_level_pct = (equity / margin_used * 100.0) if margin_used > 0 else 999.0
        
        return {
            "balance": round(balance, 2),
            "equity": round(equity, 2),
            "realized_pl": round(realized_pl, 2),
            "unrealized_pl": round(total_unrealized_pl, 2),
            "total_pl": round(total_pl, 2),
            "total_notional": round(total_notional_exposure, 2),
            "effective_leverage": round(effective_leverage, 2),
            "margin_used": round(margin_used, 2),
            "free_margin": round(free_margin, 2),
            "margin_level_pct": round(margin_level_pct, 2),
            "gross_buying_power": round(gross_buying_power, 2),
            "buying_power": round(available_buying_power, 2),
            "cash": round(balance, 2)
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
                "qty": qty,
                "side": "LONG" if qty > 0 else "SHORT",
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
        
        # Microstructure Entry Check: Veto on strong opposing LOB Imbalance
        if action == "BUY" and obi_rho < -0.3 and not evaluated_order.get("is_take_profit"):
            evaluated_order["oms_state"] = "REJECTED_LOB_IMBALANCE"
            evaluated_order["oms_detail"] = f"Opposing sell-side LOB Imbalance rho ({obi_rho:.2f}) < -0.3 threshold."
            return evaluated_order
        elif action == "SELL" and obi_rho > 0.3 and not evaluated_order.get("is_take_profit"):
            evaluated_order["oms_state"] = "REJECTED_LOB_IMBALANCE"
            evaluated_order["oms_detail"] = f"Opposing buy-side LOB Imbalance rho ({obi_rho:.2f}) > 0.3 threshold."
            return evaluated_order

        symbol = evaluated_order["instrument"]
        alloc_pct = evaluated_order["portfolio_allocation_pct"]
        atr = evaluated_order.get("atr", current_price * 0.015)

        # Market Session Check
        from execution.market_session import is_market_session_open
        is_open, session_reason, _ = is_market_session_open(symbol)
        if not is_open and not evaluated_order.get("is_take_profit"):
            evaluated_order["oms_state"] = "REJECTED_MARKET_CLOSED"
            evaluated_order["oms_detail"] = session_reason
            return evaluated_order
        
        state = self._read_state()
        acc = self.get_account_state()
        equity = acc["equity"]
        
        if current_price <= 0:
            evaluated_order["oms_state"] = "FAILED"
            evaluated_order["oms_detail"] = "Invalid price."
            return evaluated_order
            
        is_crypto = symbol in ["BTC-USD", "ETH-USD"]
        asset_class = "crypto" if is_crypto else "stock"
        dynamic_lev = float(evaluated_order.get("dynamic_leverage", config.FUTURES_LEVERAGE))
        risk_budget = float(evaluated_order.get("risk_budget_usd", 10.0))
        
        if not is_crypto:
            # US Futures / Stock: Risk budget based sizing with dynamic leverage
            stop_distance = max(0.01, atr * 2.0)
            target_qty_abs = max(0.1, (risk_budget / stop_distance) * (dynamic_lev / 5.0))
            notional_value = target_qty_abs * current_price
        else:
            # Crypto: Conviction-scaled Kelly with dynamic leverage
            notional_value = equity * alloc_pct * dynamic_lev
            target_qty_abs = notional_value / current_price
            
        order_qty = target_qty_abs if action == "BUY" else -target_qty_abs
        
        # Microstructure Friction & Slippage Model
        spread = max(0.01, current_price * 0.0002)
        half_spread = spread / 2.0
        obi_penalty = max(0.0, -obi_rho * 0.0001 * current_price) if action == "BUY" else max(0.0, obi_rho * 0.0001 * current_price)
        slippage = max(0.005, (current_price * 0.0001) + obi_penalty)
        fill_price = round(current_price + half_spread + slippage if action == "BUY" else current_price - half_spread - slippage, 4)
        commission = max(1.0, abs(order_qty) * 0.005)

        from middleware.event_bus import event_bus, to_iso8601

        pos = state["positions"].get(symbol)
        now_iso = to_iso8601()
        
        if pos:
            old_qty = pos["qty"]
            old_entry = pos["entry_price"]
            old_trade_id = pos.get("trade_id", "trd_" + uuid.uuid4().hex[:8])
            old_opened_at = pos.get("opened_at", now_iso)
            
            # Prevent runaway stacking in the same direction
            if (old_qty > 0 and order_qty > 0) or (old_qty < 0 and order_qty < 0):
                if abs(old_qty) >= 10.0:
                    evaluated_order["oms_state"] = "REJECTED_MAX_POSITION"
                    evaluated_order["oms_detail"] = f"Max position limit reached for {symbol} ({old_qty})."
                    return evaluated_order
            
            # Position reduction or reversal
            if (old_qty > 0 and order_qty < 0) or (old_qty < 0 and order_qty > 0):
                closing_qty = min(abs(old_qty), abs(order_qty))
                realized_pnl = round(((fill_price - old_entry) * closing_qty * (1 if old_qty > 0 else -1)) - commission, 2)
                state["balance"] = round(state.get("balance", 1000.0) + realized_pnl, 2)
                state["realized_pl"] = round(state.get("realized_pl", 0.0) + realized_pnl, 2)
                pos["realized_pnl"] = round(pos.get("realized_pnl", 0.0) + realized_pnl, 2)
            
            new_qty = old_qty + order_qty
            
            # Position flip or complete close
            if abs(new_qty) < 0.0001 or (old_qty > 0 and new_qty < 0) or (old_qty < 0 and new_qty > 0):
                # Emit closed event for the previous position
                event_bus.publish_position_update(
                    trade_id=old_trade_id,
                    symbol=symbol,
                    side="long" if old_qty > 0 else "short",
                    size=abs(old_qty),
                    leverage=pos.get("leverage", dynamic_lev),
                    entry_price=old_entry,
                    exit_price=fill_price,
                    mark_price=fill_price,
                    status="closed",
                    opened_at=old_opened_at,
                    closed_at=now_iso,
                    unrealized_pnl=0.0,
                    realized_pnl=pos.get("realized_pnl")
                )
                
                if abs(new_qty) < 0.0001:
                    del state["positions"][symbol]
                else:
                    # Direction flip: create new position record for the reversed direction
                    new_trade_id = "trd_" + uuid.uuid4().hex[:8]
                    state["positions"][symbol] = {
                        "trade_id": new_trade_id,
                        "symbol": symbol,
                        "qty": new_qty,
                        "entry_price": fill_price,
                        "current_price": current_price,
                        "leverage": dynamic_lev,
                        "atr_trailing_stop": fill_price - (0.02 * fill_price) if new_qty > 0 else fill_price + (0.02 * fill_price),
                        "unrealized_pl": 0.0,
                        "unrealized_plpc": 0.0,
                        "realized_pnl": 0.0,
                        "opened_at": now_iso
                    }
                    event_bus.publish_position_update(
                        trade_id=new_trade_id,
                        symbol=symbol,
                        side="long" if new_qty > 0 else "short",
                        size=abs(new_qty),
                        leverage=dynamic_lev,
                        entry_price=fill_price,
                        mark_price=current_price,
                        status="open",
                        opened_at=now_iso,
                        unrealized_pnl=0.0,
                        realized_pnl=0.0
                    )
            else:
                # Adding to existing position in same direction
                new_entry = ((abs(old_qty) * old_entry) + (abs(order_qty) * fill_price)) / abs(new_qty)
                pos["qty"] = new_qty
                pos["entry_price"] = new_entry
                pos["current_price"] = current_price
                event_bus.publish_position_update(
                    trade_id=old_trade_id,
                    symbol=symbol,
                    side="long" if new_qty > 0 else "short",
                    size=abs(new_qty),
                    leverage=pos.get("leverage", dynamic_lev),
                    entry_price=new_entry,
                    mark_price=current_price,
                    status="open",
                    opened_at=old_opened_at,
                    unrealized_pnl=pos.get("unrealized_pl", 0.0),
                    realized_pnl=pos.get("realized_pnl", 0.0)
                )
                
        else:
            # Brand new position
            trade_id = "trd_" + uuid.uuid4().hex[:8]
            state["positions"][symbol] = {
                "trade_id": trade_id,
                "symbol": symbol,
                "qty": order_qty,
                "entry_price": fill_price,
                "current_price": current_price,
                "leverage": dynamic_lev,
                "atr_trailing_stop": fill_price - (0.02 * fill_price) if order_qty > 0 else fill_price + (0.02 * fill_price),
                "unrealized_pl": 0.0,
                "unrealized_plpc": 0.0,
                "realized_pnl": 0.0,
                "opened_at": now_iso
            }
            event_bus.publish_position_update(
                trade_id=trade_id,
                symbol=symbol,
                side="long" if order_qty > 0 else "short",
                size=abs(order_qty),
                leverage=dynamic_lev,
                entry_price=fill_price,
                mark_price=current_price,
                status="open",
                opened_at=now_iso,
                unrealized_pnl=0.0,
                realized_pnl=0.0
            )
            
        tot_unrealized = sum(p.get("unrealized_pl", 0.0) for p in state["positions"].values())
        balance = state.get("balance", 1000.0)
        state["balance"] = round(balance, 2)
        state["unrealized_pl"] = round(tot_unrealized, 2)
        state["equity"] = round(balance + tot_unrealized, 2)
        state["total_pl"] = round(state.get("realized_pl", 0.0) + tot_unrealized, 2)
        self._write_state(state)
        
        evaluated_order["oms_state"] = "SUBMITTED"
        evaluated_order["alpaca_order_id"] = "sim_" + uuid.uuid4().hex[:8]
        evaluated_order["notional_value"] = notional_value
        evaluated_order["price"] = fill_price
        evaluated_order["qty"] = round(order_qty, 4)
        evaluated_order["quantity"] = round(abs(order_qty), 4)
        evaluated_order["timestamp_executed"] = time.time()
        evaluated_order["realized_pnl"] = 0.0

        # Publish entry fill execution log
        event_bus.publish_execution_log(
            level="fill",
            category="entry_fill",
            symbol=symbol,
            message=f"Order filled for {action} {abs(order_qty):.4f} {symbol} @ ${fill_price:.2f}",
            order_id=evaluated_order.get("order_id")
        )

        return evaluated_order

