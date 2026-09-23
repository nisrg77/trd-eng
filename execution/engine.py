"""
execution/engine.py — Execution & Sizing Engine (EE)

Pulls standard signals from the Core Brain, applies position sizing
logic (Kelly Criterion, scaled by confidence), and constructs a proposed
order for the Risk Guard.
"""

from __future__ import annotations
import uuid
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

# TRDENG Pipeline Cadence Contract
# Layer                          | Runs on           | Source file
# ------------------------------ | ------------------ | -------------------------
# HMM regime classification      | per bar close      | brain/*.py
# Meta-Aggregator blend          | per bar close      | brain/meta_aggregator.py
# IFF opposing-flow veto/scale   | per bar close      | alpha_overlay/iff.py (inline, fresh at call time)
# Dead-day percentile filter     | per bar close      | data_pipeline/dead_day_filter.py
# Dynamic leverage curve         | per order proposal | goals/goal_module.py
# Goal/risk gating               | per order proposal | goals/goal_module.py
# Micro-buffer dwell veto        | per order proposal | alpha_overlay/iff.py (holds hold_ms)
# LOB imbalance filter           | per order proposal | execution/simulated_oms.py
# VPOC TP snapping               | per fill / per bar | execution/simulated_oms.py

def _log_rejection(
    instrument: str,
    asset_class: str,
    gate: str,
    reason: str,
    final_action: str,
    direction: float,
    effective_conviction: float,
    goal_state=None,
) -> None:
    """Fire-and-forget: write a gate rejection record to MongoDB gate_rejections."""
    try:
        from middleware.db_manager import mongo_db
        from goals.goal_module import load_state
        state = goal_state or load_state()
        ac_key = "crypto" if asset_class == "crypto" else "stock"
        bucket = state.crypto if ac_key == "crypto" else state.stock
        mongo_db.save_gate_rejection({
            "instrument": instrument,
            "asset_class": asset_class,
            "gate": gate,
            "reason": reason,
            "final_action": final_action,
            "signal_direction": direction,
            "effective_conviction": effective_conviction,
            "daily_trades_used": bucket.trades_today,
            "monthly_pnl_usd": bucket.realized_pnl_this_month_usd,
        })
    except Exception:
        pass  # Never block the trade path


class ExecutionEngine:
    def __init__(self):
        pass

    def size_order(self, signal: dict, instrument_data: dict) -> dict | None:
        """
        Calculates position size and generates a proposed order.
        If current position is highly profitable, takes partial profit instead.
        Constructs and records a single DecisionTrace for every proposed trade.
        """
        from core.decision_trace import DecisionTrace, decision_trace_buffer
        
        instr = signal.get("instrument", "UNKNOWN")
        confidence = float(signal.get("confidence_score", 0.0))
        direction = float(signal.get("direction_magnitude", 0.0))
        now = time.time()
        
        # Pull active risk profile settings
        prof_name = getattr(config, "ACTIVE_RISK_PROFILE", "Balanced")
        profile = config.RISK_PROFILES.get(prof_name, config.RISK_PROFILES["Balanced"])
        
        # 1. Check for Partial Take-Profit opportunities
        if instr in instrument_data:
            pos = instrument_data[instr]
            if pos.get("unrealized_plpc", 0.0) >= profile["PARTIAL_TP_THRESHOLD_PCT"]:
                action = "SELL" if pos.get("exposure_pct", 0) > 0 else "BUY"
                alloc_pct = pos.get("exposure_pct", 0) * profile["PARTIAL_TP_SELL_PCT"]
                order_id = "ord_tp_" + uuid.uuid4().hex[:8]
                
                trace = DecisionTrace(
                    symbol=instr,
                    timestamp=now,
                    s_composite_raw=direction,
                    s_flow=0.0,
                    iff_veto=False,
                    iff_scaled_signal=direction,
                    dead_day=False,
                    dead_day_filter_mode="Take Profit",
                    effective_conviction=1.0,
                    leverage=1.0,
                    risk_budget_usd=0.0,
                    gate_ceiling_blocked=False,
                    gate_daily_loss_blocked=False,
                    gate_monthly_dd_blocked=False,
                    micro_buffer_preempted=False,
                    micro_buffer_reason="None",
                    lob_imbalance_blocked=False,
                    final_action="EXECUTED"
                )
                decision_trace_buffer.record_trace(trace)

                return {
                    "order_id": order_id,
                    "signal_id": signal.get("signal_id"),
                    "instrument": instr,
                    "action": action,
                    "order_type": "MARKET",
                    "portfolio_allocation_pct": alloc_pct,
                    "confidence": 1.0,
                    "timestamp_proposed": now,
                    "is_take_profit": True,
                    "decision_trace": trace.to_dict()
                }

        # 2. Normal Signal Processing
        from execution.market_session import is_market_session_open
        is_open, _, _ = is_market_session_open(instr)
        if not is_open:
            return None # Skip entry orders outside market hours

        is_crypto = instr in getattr(config, "CRYPTO_INSTRUMENTS", ["BTC-USD", "ETH-USD"])
        asset_class = "crypto" if is_crypto else "stock"

        # ── Dead-Day & Conviction Evaluation ─────────────────────────────────
        dead_day_result = signal.get("dead_day_result")
        if not dead_day_result:
            from data_pipeline.dead_day_filter import compute_dead_day_and_conviction
            dead_day_result = {
                "is_dead_day": False,
                "dead_day_reason": "Live Signal",
                "raw_conviction": confidence,
                "effective_conviction": confidence,
                "rvol": 1.0,
                "range_atr_ratio": 1.0,
                "filter_mode": "Static Fallback"
            }

        from goals.goal_module import evaluate_trade
        decision = evaluate_trade(asset_class, dead_day_result)
        
        # Determine gate blocks
        is_dead_day = bool(dead_day_result.get("is_dead_day", False))
        filter_mode = dead_day_result.get("filter_mode", "Static Fallback")
        effective_conviction = float(dead_day_result.get("effective_conviction", confidence))
        
        flow_score = 0.0
        iff_veto = False
        scaled_signal = direction

        try:
            from alpha_overlay.iff import get_flow_score
            import config as _cfg
            obi_rho = float(signal.get("obi_rho", signal.get("features", {}).get("order_book_imbalance", 0.0)))
            flow_score = float(get_flow_score(instr, obi_rho))
            # Must match iff.py: threshold 0.65, crypto exempt from hard veto
            veto_thresh = getattr(_cfg, "IFF_VETO_THRESHOLD", 0.65)
            is_crypto = instr in getattr(_cfg, "CRYPTO_INSTRUMENTS", [])
            if not is_crypto:
                if (direction > 0 and flow_score < -veto_thresh) or (direction < 0 and flow_score > veto_thresh):
                    iff_veto = True
            # Soft scale capped at ±30% (matches iff.py)
            scaled_signal = direction * (1.0 + 0.3 * flow_score)
        except Exception:
            pass

        if not decision.allowed:
            block_reason = "BLOCKED_DEAD_DAY" if is_dead_day else "BLOCKED_GOAL_GATE"
            trace = DecisionTrace(
                symbol=instr,
                timestamp=now,
                s_composite_raw=direction,
                s_flow=flow_score,
                iff_veto=iff_veto,
                iff_scaled_signal=scaled_signal,
                dead_day=is_dead_day,
                dead_day_filter_mode=filter_mode,
                effective_conviction=effective_conviction,
                leverage=decision.leverage,
                risk_budget_usd=decision.risk_budget_usd,
                gate_ceiling_blocked=getattr(decision, "ceiling_blocked", False),
                gate_daily_loss_blocked=getattr(decision, "daily_loss_blocked", False),
                gate_monthly_dd_blocked=getattr(decision, "monthly_dd_blocked", False),
                micro_buffer_preempted=False,
                micro_buffer_reason="None",
                lob_imbalance_blocked=False,
                final_action=block_reason
            )
            decision_trace_buffer.record_trace(trace)
            _log_rejection(
                instrument=instr,
                asset_class=asset_class,
                gate="GOAL_GATE",
                reason=decision.reason,
                final_action=block_reason,
                direction=direction,
                effective_conviction=effective_conviction,
            )
            return None

        if effective_conviction < getattr(config, "MIN_CONFIDENCE_THRESHOLD", 0.35):
            trace = DecisionTrace(
                symbol=instr,
                timestamp=now,
                s_composite_raw=direction,
                s_flow=flow_score,
                iff_veto=iff_veto,
                iff_scaled_signal=scaled_signal,
                dead_day=is_dead_day,
                dead_day_filter_mode=filter_mode,
                effective_conviction=effective_conviction,
                leverage=decision.leverage,
                risk_budget_usd=decision.risk_budget_usd,
                gate_ceiling_blocked=False,
                gate_daily_loss_blocked=False,
                gate_monthly_dd_blocked=False,
                micro_buffer_preempted=False,
                micro_buffer_reason="Low conviction",
                lob_imbalance_blocked=False,
                final_action="BLOCKED_LOW_CONVICTION"
            )
            decision_trace_buffer.record_trace(trace)
            _log_rejection(
                instrument=instr,
                asset_class=asset_class,
                gate="LOW_CONVICTION",
                reason=f"effective_conviction {effective_conviction:.4f} < threshold {getattr(config, 'MIN_CONFIDENCE_THRESHOLD', 0.35)}",
                final_action="BLOCKED_LOW_CONVICTION",
                direction=direction,
                effective_conviction=effective_conviction,
            )
            return None

        allocation_pct = effective_conviction * profile["KELLY_FRACTION"]
        allocation_pct = min(allocation_pct, profile["MAX_POSITION_SIZE_PCT"])
        flow_mult = 1.0 + flow_score
        allocation_pct = min(allocation_pct * flow_mult, profile["MAX_POSITION_SIZE_PCT"])

        action = "BUY" if direction > 0 else "SELL" if direction < 0 else "HOLD"
        if action == "HOLD" or allocation_pct < 0.01:
            return None

        if instr in instrument_data:
            existing_pos = instrument_data[instr]
            existing_side = existing_pos.get("side", "LONG" if existing_pos.get("exposure_pct", 0) > 0 else None)
            if existing_side == action:
                return None

        # ── Micro-Buffer Hold Queue & Dwell-Time Veto Check ──────────────────
        preempted = False
        micro_reason = "Passed micro-buffer evaluation"
        try:
            from alpha_overlay.iff import hold_and_evaluate_micro_buffer
            hold_ms = getattr(config, "MICRO_BUFFER_HOLD_MS", 50.0)
            dwell_ms = getattr(config, "MICRO_BUFFER_DWELL_MS", 10.0)
            
            preempted, micro_reason = hold_and_evaluate_micro_buffer(instr, action, hold_ms=hold_ms, dwell_ms=dwell_ms)
        except Exception as e:
            micro_reason = str(e)

        final_act = "BLOCKED_MICRO_BUFFER" if preempted else "EXECUTED"

        trace = DecisionTrace(
            symbol=instr,
            timestamp=now,
            s_composite_raw=direction,
            s_flow=flow_score,
            iff_veto=iff_veto,
            iff_scaled_signal=scaled_signal,
            dead_day=is_dead_day,
            dead_day_filter_mode=filter_mode,
            effective_conviction=effective_conviction,
            leverage=decision.leverage,
            risk_budget_usd=decision.risk_budget_usd,
            gate_ceiling_blocked=getattr(decision, "ceiling_blocked", False),
            gate_daily_loss_blocked=getattr(decision, "daily_loss_blocked", False),
            gate_monthly_dd_blocked=getattr(decision, "monthly_dd_blocked", False),
            micro_buffer_preempted=preempted,
            micro_buffer_reason=micro_reason,
            lob_imbalance_blocked=False,
            final_action=final_act
        )
        decision_trace_buffer.record_trace(trace)

        if preempted:
            _log_rejection(
                instrument=instr,
                asset_class=asset_class,
                gate="MICRO_BUFFER",
                reason=micro_reason,
                final_action="BLOCKED_MICRO_BUFFER",
                direction=direction,
                effective_conviction=effective_conviction,
            )
            return None

        order_id = "ord_" + uuid.uuid4().hex[:8]
        proposed_order = {
            "order_id": order_id,
            "signal_id": signal.get("signal_id"),
            "instrument": instr,
            "action": action,
            "order_type": "MARKET",
            "portfolio_allocation_pct": allocation_pct,
            "confidence": confidence,
            "conviction_score": effective_conviction,
            "dynamic_leverage": decision.leverage,
            "risk_budget_usd": decision.risk_budget_usd,
            "timestamp_proposed": now,
            "is_take_profit": False,
            "decision_trace": trace.to_dict()
        }

        return proposed_order


