"""
strategies/ai/onnx_policy_plugin.py — Frozen ONNX Policy Plugin & Shadow Mode Engine

Runs pre-trained, frozen RL policies inside the live kernel in SHADOW MODE:
1. Pure Inference Engine: Uses onnxruntime and numpy only (Zero PyTorch / SB3 in live path).
2. Schema Hash Gate: Verifies model_meta.json feature-schema hash against live standardizer on load.
   Refuses execution and raises critical alert on any feature mismatch.
3. Sub-millisecond Execution: Stays well below the 30ms StrategyValidator limit.
4. Safe Shadow Mode (Default): Emits signals to decision_trace.jsonl with tag "rl_shadow".
   Never forwards intents to the sleeve manager or execution router.
5. Shadow PnL Tracker: Simulates realistic execution fills using execution/cost_model.py
   to track daily hypothetical PnL against baselines.
"""

from __future__ import annotations
import os
import json
import time
import math
import hashlib
import logging
import threading
from typing import Dict, Any, Optional, List, Tuple

import numpy as np
import pandas as pd
import onnxruntime as ort

from strategies.base_strategy import BaseStrategy
from core.signal_packet import SignalPacket
from core.order_intent import OrderIntent, OrderLeg, OrderSide, OrderType, IntentType, PositionContext
from data_pipeline.feature_standardizer import compute_standard_features
from core.decision_trace import decision_trace_buffer
from execution.cost_model import cost_model, CostModel
from middleware.system_monitor import system_monitor

log = logging.getLogger(__name__)

EXPECTED_FEATURE_NAMES = [
    "log_ret_1",
    "log_ret_3",
    "log_ret_5",
    "log_ret_12",
    "rsi_14_centered",
    "bb_dist_atr",
    "bb_width_atr",
    "adx_14_centered",
    "realized_vol_20",
    "current_position",
    "unrealized_pnl_atr",
    "bars_in_trade_norm"
]

EXPECTED_MARKET_FEATURES = EXPECTED_FEATURE_NAMES[:9]


def compute_live_schema_hash() -> str:
    """Computes the expected canonical SHA-256 hash for the feature schema."""
    encoded = json.dumps(EXPECTED_FEATURE_NAMES).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()[:16]


# ── Shadow PnL Tracker ────────────────────────────────────────────────────────
class ShadowPnLTracker:
    """
    Simulates hypothetical fills for logged shadow signals using cost_model.py,
    tracking daily and cumulative shadow performance without placing real orders.
    """

    def __init__(self, initial_equity: float = 10000.0) -> None:
        self._lock = threading.RLock()
        self.initial_equity = initial_equity
        self.equity = initial_equity
        self.peak_equity = initial_equity
        self.current_position = 0.0
        self.entry_price = 0.0
        self.trades_count = 0
        self.total_costs_usd = 0.0
        self.daily_records: List[Dict[str, Any]] = []
        self.history: List[Dict[str, Any]] = []

    def record_shadow_step(
        self,
        symbol: str,
        target_action: int,  # 0: Short, 1: Flat, 2: Long
        current_price: float,
        atr: float,
        timestamp: float = 0.0
    ) -> Dict[str, Any]:
        """
        Simulates fill and cost for a shadow step.
        """
        with self._lock:
            target_pos = {0: -1.0, 1: 0.0, 2: 1.0}.get(target_action, 0.0)
            old_pos = self.current_position
            ts = timestamp or time.time()

            cost_res = cost_model.calculate_cost(
                price=current_price,
                atr=atr,
                current_pos=old_pos,
                target_pos=target_pos,
                is_taker=True,
                notional_usd=1000.0
            )

            cost_usd = cost_res.total_cost_usd
            self.total_costs_usd += cost_usd

            # Calculate step return
            pnl_step_usd = 0.0
            if abs(old_pos) > 1e-7 and self.entry_price > 0:
                pnl_step_usd = (current_price - self.entry_price) * old_pos * (1000.0 / self.entry_price)

            if target_pos != old_pos:
                self.trades_count += 1
                self.current_position = target_pos
                self.entry_price = current_price if abs(target_pos) > 1e-7 else 0.0

            net_pnl = pnl_step_usd - cost_usd
            self.equity += net_pnl
            self.peak_equity = max(self.peak_equity, self.equity)
            drawdown_pct = max(0.0, (self.peak_equity - self.equity) / self.peak_equity) * 100.0

            record = {
                "timestamp": ts,
                "symbol": symbol,
                "action": target_action,
                "position": target_pos,
                "price": current_price,
                "cost_usd": cost_usd,
                "net_pnl_usd": round(net_pnl, 2),
                "equity": round(self.equity, 2),
                "drawdown_pct": round(drawdown_pct, 2),
                "trades_count": self.trades_count
            }
            self.history.append(record)
            return record

    def get_summary(self) -> Dict[str, Any]:
        with self._lock:
            total_return_pct = ((self.equity / self.initial_equity) - 1.0) * 100.0
            max_dd = max([h["drawdown_pct"] for h in self.history], default=0.0)
            return {
                "initial_equity": self.initial_equity,
                "current_equity": round(self.equity, 2),
                "total_return_pct": round(total_return_pct, 2),
                "max_drawdown_pct": round(max_dd, 2),
                "trades_count": self.trades_count,
                "total_costs_usd": round(self.total_costs_usd, 2)
            }


# Global shadow PnL tracker singleton
shadow_pnl_tracker = ShadowPnLTracker()


# ── ONNX Policy Strategy Plugin ───────────────────────────────────────────────
class ONNXPolicyPlugin(BaseStrategy):
    """
    Frozen ONNX RL policy strategy plugin running in shadow mode by default.
    """

    def __init__(
        self,
        strategy_id: str = "ai_rl_onnx_01",
        name: str = "RL PPO Policy",
        asset_class: str = "crypto",
        onnx_model_path: Optional[str] = None,
        meta_path: Optional[str] = None,
        shadow_mode: bool = True,
        sleeve_id: str = "sleeve_ai_shadow",
        params: Optional[Dict[str, Any]] = None
    ) -> None:
        super().__init__(
            strategy_id=strategy_id,
            name=name,
            asset_class=asset_class,
            params=params or {},
            is_active=True
        )
        self.sleeve_id = sleeve_id
        self.shadow_mode = shadow_mode
        self.onnx_model_path = onnx_model_path
        self.meta_path = meta_path or (onnx_model_path.replace(".onnx", "_meta.json") if onnx_model_path else None)

        self._session: Optional[ort.InferenceSession] = None
        self._meta: Dict[str, Any] = {}
        self._norm_stats: Dict[str, Dict[str, float]] = {}
        self.is_loaded = False

        self._bars_in_trade = 0
        self._last_action = 1  # 1 = Flat
        self._min_holding_bars = int(self.params.get("min_holding_bars", 3))
        self._allocation_usd = float(self.params.get("allocation_usd", 1000.0))

        if self.onnx_model_path and os.path.exists(self.onnx_model_path):
            self._load_model()

    def _load_model(self) -> None:
        """
        Loads ONNX graph and validates schema hash against canonical definition.
        """
        if not self.meta_path or not os.path.exists(self.meta_path):
            msg = f"Model metadata missing for {self.onnx_model_path}!"
            log.critical(msg)
            system_monitor.raise_alert(
                severity="CRITICAL",
                alert_type="ONNX_LOAD_ERROR",
                message=msg,
                data={"model_path": self.onnx_model_path}
            )
            raise FileNotFoundError(msg)

        with open(self.meta_path, "r", encoding="utf-8") as f:
            self._meta = json.load(f)

        # ── Feature Schema Hash Verification ─────────────────────────────────
        expected_hash = compute_live_schema_hash()
        actual_hash = self._meta.get("feature_schema_hash", "")

        if actual_hash != expected_hash:
            msg = (
                f"CRITICAL SCHEMA MISMATCH for strategy {self.strategy_id}! "
                f"Model hash [{actual_hash}] != Live hash [{expected_hash}]. "
                "Refusing to load untrusted policy."
            )
            log.critical(msg)
            system_monitor.raise_alert(
                severity="CRITICAL",
                alert_type="SCHEMA_HASH_MISMATCH",
                message=msg,
                data={"expected": expected_hash, "actual": actual_hash}
            )
            raise ValueError(msg)

        # Load normalization statistics
        self._norm_stats = self._meta.get("normalization_stats", {})

        # Initialize ONNX Runtime session (CPUExecutionProvider only)
        opts = ort.SessionOptions()
        opts.inter_op_num_threads = 1
        opts.intra_op_num_threads = 1
        opts.enable_cpu_mem_arena = False
        self._session = ort.InferenceSession(
            self.onnx_model_path,
            sess_options=opts,
            providers=["CPUExecutionProvider"]
        )

        self.is_loaded = True
        log.info(
            "[%s] ONNX Policy loaded successfully (Schema Hash: %s, Shadow Mode: %s)",
            self.strategy_id, actual_hash, self.shadow_mode
        )

    def _build_observation(
        self,
        df: pd.DataFrame,
        position_context: Optional[PositionContext] = None
    ) -> Optional[np.ndarray]:
        """
        Extracts causal features and position state into a normalized 12-dim observation vector.
        """
        if df.empty or len(df) < 20:
            return None

        # 1. Compute standard indicators if missing
        if "bb_middle" not in df.columns or "rsi_14" not in df.columns:
            df = compute_standard_features(df)

        close = df["close"].astype(np.float64)
        atr = df["atr_14"].clip(lower=1e-6)

        # Compute log returns
        log_ret_1 = float(np.log(close.iloc[-1] / close.iloc[-2]))
        log_ret_3 = float(np.log(close.iloc[-1] / close.iloc[-4])) if len(close) >= 4 else 0.0
        log_ret_5 = float(np.log(close.iloc[-1] / close.iloc[-6])) if len(close) >= 6 else 0.0
        log_ret_12 = float(np.log(close.iloc[-1] / close.iloc[-13])) if len(close) >= 13 else 0.0

        # Technical indicator features
        rsi_centered = (float(df["rsi_14"].iloc[-1]) - 50.0) / 50.0
        bb_dist_atr = (float(close.iloc[-1]) - float(df["bb_middle"].iloc[-1])) / float(atr.iloc[-1])
        bb_width_atr = (float(df["bb_upper"].iloc[-1]) - float(df["bb_lower"].iloc[-1])) / float(atr.iloc[-1])
        adx_centered = (float(df["adx_14"].iloc[-1]) - 25.0) / 25.0

        # 20-bar realized volatility
        rolling_rets = np.log(close / close.shift(1)).dropna()
        realized_vol = float(rolling_rets.iloc[-20:].std()) if len(rolling_rets) >= 20 else 0.01

        market_vals = [
            log_ret_1,
            log_ret_3,
            log_ret_5,
            log_ret_12,
            rsi_centered,
            bb_dist_atr,
            bb_width_atr,
            adx_centered,
            realized_vol
        ]

        # Standardize using fitted training stats
        norm_market = []
        for name, val in zip(EXPECTED_MARKET_FEATURES, market_vals):
            stat = self._norm_stats.get(name, {"mean": 0.0, "std": 1.0})
            norm = (val - stat["mean"]) / stat["std"]
            norm_market.append(np.clip(norm, -5.0, 5.0))

        # Position context features
        if position_context and position_context.is_open:
            cur_pos = 1.0 if position_context.side == OrderSide.BUY else -1.0
            unrealized_pnl_atr = (float(close.iloc[-1]) - position_context.entry_price) * cur_pos / float(atr.iloc[-1])
            bars_in_trade_norm = min(1.0, self._bars_in_trade / 50.0)
        else:
            cur_pos = 0.0
            unrealized_pnl_atr = 0.0
            bars_in_trade_norm = 0.0

        pos_vals = [cur_pos, np.clip(unrealized_pnl_atr, -5.0, 5.0), bars_in_trade_norm]

        obs_vector = np.array(norm_market + pos_vals, dtype=np.float32)

        # Validate finiteness
        if not np.all(np.isfinite(obs_vector)):
            log.warning("[%s] Non-finite observation encountered! Aborting.", self.strategy_id)
            return None

        return obs_vector.reshape(1, -1)

    def evaluate(
        self,
        symbol: str,
        df: pd.DataFrame,
        position_context: Optional[PositionContext] = None
    ) -> Optional[OrderIntent]:
        """
        Runs sub-millisecond ONNX inference.
        In SHADOW MODE: Logs shadow trace and returns None (never reaches execution router).
        """
        if not self.is_loaded or self._session is None:
            return None

        t_start = time.perf_counter()
        try:
            obs = self._build_observation(df, position_context)
            if obs is None:
                return None

            # ONNX Runtime Inference
            logits = self._session.run(None, {"observation": obs})[0][0]
            action = int(np.argmax(logits))  # 0: Short, 1: Flat, 2: Long

            # Softmax confidence
            exp_l = np.exp(logits - np.max(logits))
            probs = exp_l / np.sum(exp_l)
            conviction = float(probs[action])

            lat_ms = (time.perf_counter() - t_start) * 1000.0

        except Exception as e:
            log.error("[%s] ONNX inference error on %s: %s", self.strategy_id, symbol, e)
            return None

        # Enforce minimum holding period
        is_open = position_context and position_context.is_open
        target_pos = {0: -1.0, 1: 0.0, 2: 1.0}[action]

        if is_open:
            cur_pos = 1.0 if position_context.side == OrderSide.BUY else -1.0
            if target_pos != cur_pos and self._bars_in_trade < self._min_holding_bars:
                # Holding period active — maintain current action
                action = 2 if cur_pos > 0 else 0
                target_pos = cur_pos

        # Update bars in trade
        if target_pos != 0.0:
            self._bars_in_trade += 1
        else:
            self._bars_in_trade = 0
        self._last_action = action

        current_px = float(df["close"].iloc[-1])
        atr_val = float(df["atr_14"].iloc[-1]) if "atr_14" in df.columns else (current_px * 0.01)

        # ── SHADOW MODE ENFORCEMENT ───────────────────────────────────────────
        if self.shadow_mode:
            # 1. Simulate fill in ShadowPnLTracker
            shadow_pnl_tracker.record_shadow_step(
                symbol=symbol,
                target_action=action,
                current_price=current_px,
                atr=atr_val,
                timestamp=time.time()
            )

            # 2. Record full diagnostic audit trace with tag "rl_shadow"
            decision_trace_buffer.record_shadow_trace(
                symbol=symbol,
                strategy_id=self.strategy_id,
                sleeve_id=self.sleeve_id,
                final_action="SHADOW_LOGGED",
                expected_fee_usd=self._allocation_usd * 0.0004,
                expected_slippage_usd=self._allocation_usd * 0.0002,
                spread_cost_usd=self._allocation_usd * 0.0001,
                simulated_latency_ms=round(lat_ms, 2),
                shadow_meta_label=action,
                shadow_meta_probability=conviction
            )

            log.info(
                "[%s SHADOW] %s Action: %s (Prob: %.2f) | Latency: %.2f ms | ZERO live orders sent",
                self.strategy_id, symbol, {0: "SHORT", 1: "FLAT", 2: "LONG"}[action], conviction, lat_ms
            )

            # GUARANTEE: In shadow mode, returns None so intent NEVER reaches sleeve manager or router!
            return None

        # ── LIVE MODE (Only active when shadow_mode is explicitly False) ──────
        if action == 2:  # LONG
            return OrderIntent(
                strategy_id=self.strategy_id,
                sleeve_id=self.sleeve_id,
                intent_type=IntentType.ENTRY,
                legs=[OrderLeg(symbol=symbol, side=OrderSide.BUY, target_size_usd=self._allocation_usd)],
                conviction=conviction,
                stop_loss_price=current_px - (2.0 * atr_val),
                metadata={"tag": "rl_live", "action": "LONG", "latency_ms": lat_ms}
            )
        elif action == 0:  # SHORT
            return OrderIntent(
                strategy_id=self.strategy_id,
                sleeve_id=self.sleeve_id,
                intent_type=IntentType.ENTRY,
                legs=[OrderLeg(symbol=symbol, side=OrderSide.SELL, target_size_usd=self._allocation_usd)],
                conviction=conviction,
                stop_loss_price=current_px + (2.0 * atr_val),
                metadata={"tag": "rl_live", "action": "SHORT", "latency_ms": lat_ms}
            )
        elif action == 1 and is_open:  # EXIT TO FLAT
            exit_side = OrderSide.SELL if position_context.side == OrderSide.BUY else OrderSide.BUY
            return OrderIntent(
                strategy_id=self.strategy_id,
                sleeve_id=self.sleeve_id,
                intent_type=IntentType.EXIT,
                legs=[OrderLeg(symbol=symbol, side=exit_side, target_size_usd=self._allocation_usd)],
                metadata={"tag": "rl_live", "action": "EXIT", "latency_ms": lat_ms}
            )

        return None

    def generate_signal(self, symbol: str, df: pd.DataFrame) -> Optional[SignalPacket]:
        """BaseStrategy protocol implementation."""
        if not self.is_loaded:
            return None

        obs = self._build_observation(df, None)
        if obs is None:
            return None

        logits = self._session.run(None, {"observation": obs})[0][0]
        action = int(np.argmax(logits))
        exp_l = np.exp(logits - np.max(logits))
        conviction = float(exp_l[action] / np.sum(exp_l))

        dir_val = {0: -1.0, 1: 0.0, 2: 1.0}[action]
        return SignalPacket(
            strategy_id=self.strategy_id,
            asset_class=self.asset_class,
            symbol=symbol,
            direction=dir_val,
            conviction=conviction,
            metadata={"tag": "rl_shadow" if self.shadow_mode else "rl_live"}
        )
