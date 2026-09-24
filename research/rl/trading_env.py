"""
research/rl/trading_env.py — Cost-Aware Gymnasium Trading Environment

Strictly causal, no-lookahead RL environment for offline training:
1. Observation Space (12-dim Box):
   - Causal market features (log returns lags 1, 3, 5, 12, RSI-14, ATR-distance to BB, BB width, ADX-14, 20-bar realized vol).
   - Position state (current position, unrealized PnL in ATR units, bars in trade).
   - Standardized via ObservationNormalizer fit strictly on TRAIN split.
2. Action Space (Discrete(3)):
   - 0 = Short (-1.0), 1 = Flat (0.0), 2 = Long (+1.0).
   - Enforces configurable min_holding_bars to prevent churn.
3. Execution Timing (Zero Lookahead):
   - Decision made at bar t close; fill executed at bar t+1 open.
4. Transaction Costs:
   - Evaluated via execution/cost_model.py (taker fee, spread, ATR slippage).
5. Reward Formulation:
   - Position * log-return - transaction_costs - drawdown_penalty - turnover_penalty.
   - Guaranteed: Flat policy yields reward exactly 0.0.
"""

from __future__ import annotations
import os
import json
import math
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

from data_pipeline.feature_standardizer import compute_standard_features
from execution.cost_model import CostModel, CostModelConfig, cost_model

log = logging.getLogger(__name__)

MARKET_FEATURE_NAMES = [
    "log_ret_1",
    "log_ret_3",
    "log_ret_5",
    "log_ret_12",
    "rsi_14_centered",
    "bb_dist_atr",
    "bb_width_atr",
    "adx_14_centered",
    "realized_vol_20"
]

ALL_FEATURE_NAMES = MARKET_FEATURE_NAMES + [
    "current_position",
    "unrealized_pnl_atr",
    "bars_in_trade_norm"
]

ACTION_MAP = {
    0: -1.0,  # SHORT
    1: 0.0,   # FLAT
    2: 1.0    # LONG
}


class ObservationNormalizer:
    """
    Fits feature standardization (mean, std) on the training split only,
    and serializes/deserializes stats to disk.
    """

    def __init__(self, stats: Optional[Dict[str, Dict[str, float]]] = None) -> None:
        self.stats = stats or {}

    def fit(self, df: pd.DataFrame) -> None:
        """Computes mean and std for each market feature on train split."""
        self.stats = {}
        for col in MARKET_FEATURE_NAMES:
            if col in df.columns:
                vals = df[col].dropna().values
                mean_val = float(np.mean(vals)) if len(vals) > 0 else 0.0
                std_val = float(np.std(vals)) if len(vals) > 0 else 1.0
                self.stats[col] = {
                    "mean": mean_val,
                    "std": max(1e-6, std_val)
                }
            else:
                self.stats[col] = {"mean": 0.0, "std": 1.0}

    def normalize_market_features(self, row: pd.Series) -> np.ndarray:
        """Transforms a single bar's market features using fitted stats."""
        norm_vals = []
        for col in MARKET_FEATURE_NAMES:
            raw_val = float(row.get(col, 0.0))
            stat = self.stats.get(col, {"mean": 0.0, "std": 1.0})
            norm = (raw_val - stat["mean"]) / stat["std"]
            norm_vals.append(np.clip(norm, -5.0, 5.0))
        return np.array(norm_vals, dtype=np.float32)

    def save(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.stats, f, indent=2)

    @classmethod
    def load(cls, filepath: str) -> ObservationNormalizer:
        with open(filepath, "r", encoding="utf-8") as f:
            stats = json.load(f)
        return cls(stats)


def prepare_market_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes standard causal features and log-return lags on OHLCV data.
    """
    out = compute_standard_features(df)
    close = out["close"].astype(np.float64)

    # 1. Log Returns over multiple lags
    out["log_ret_1"] = np.log(close / close.shift(1)).fillna(0.0)
    out["log_ret_3"] = np.log(close / close.shift(3)).fillna(0.0)
    out["log_ret_5"] = np.log(close / close.shift(5)).fillna(0.0)
    out["log_ret_12"] = np.log(close / close.shift(12)).fillna(0.0)

    # 2. RSI centered around 0
    out["rsi_14_centered"] = (out["rsi_14"] - 50.0) / 50.0

    # 3. ATR-normalized distance to BB middle and BB width
    atr = out["atr_14"].clip(lower=1e-6)
    out["bb_dist_atr"] = (close - out["bb_middle"]) / atr
    out["bb_width_atr"] = (out["bb_upper"] - out["bb_lower"]) / atr

    # 4. ADX centered
    out["adx_14_centered"] = (out["adx_14"] - 25.0) / 25.0

    # 5. Realized Volatility (rolling 20 std of log returns)
    out["realized_vol_20"] = out["log_ret_1"].rolling(20, min_periods=1).std().fillna(0.01)

    return out


@dataclass
class TradingEnvConfig:
    initial_equity: float = 10000.0
    min_holding_bars: int = 5
    drawdown_penalty_weight: float = 0.1
    turnover_penalty_weight: float = 0.001
    cost_config: CostModelConfig = field(default_factory=CostModelConfig)
    notional_usd: float = 1000.0


class TradingEnv(gym.Env):
    """
    Cost-aware, zero-lookahead Gymnasium trading environment.
    """

    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        df: pd.DataFrame,
        normalizer: Optional[ObservationNormalizer] = None,
        config: Optional[TradingEnvConfig] = None
    ) -> None:
        super().__init__()
        self.config = config or TradingEnvConfig()
        self.cost_model = CostModel(self.config.cost_config)

        # Precompute causal features
        self.df = prepare_market_features(df).reset_index(drop=True)
        self.normalizer = normalizer or ObservationNormalizer()

        # Define Gym spaces
        self.action_space = spaces.Discrete(3)  # 0: Short, 1: Flat, 2: Long
        self.observation_space = spaces.Box(
            low=-5.0,
            high=5.0,
            shape=(len(ALL_FEATURE_NAMES),),
            dtype=np.float32
        )

        # State tracking
        self.current_step = 0
        self.max_steps = len(self.df) - 1
        self.current_position = 0.0  # -1.0, 0.0, 1.0
        self.entry_price = 0.0
        self.bars_in_trade = 0
        self.equity = self.config.initial_equity
        self.peak_equity = self.config.initial_equity
        self.trade_count = 0
        self.total_costs_usd = 0.0

    def reset(
        self,
        seed: Optional[int] = None,
        options: Optional[Dict[str, Any]] = None
    ) -> Tuple[np.ndarray, Dict[str, Any]]:
        super().reset(seed=seed)
        
        # Start after warm-up bars to ensure features are stable
        warmup_bars = 20
        self.current_step = warmup_bars
        self.current_position = 0.0
        self.entry_price = 0.0
        self.bars_in_trade = 0
        self.equity = self.config.initial_equity
        self.peak_equity = self.config.initial_equity
        self.trade_count = 0
        self.total_costs_usd = 0.0

        obs = self._get_observation()
        info = {
            "step": self.current_step,
            "equity": self.equity,
            "position": self.current_position
        }
        return obs, info

    def _get_observation(self) -> np.ndarray:
        row = self.df.iloc[self.current_step]
        market_feats = self.normalizer.normalize_market_features(row)

        # Position state features
        close = float(row["close"])
        atr = max(1e-6, float(row["atr_14"]))
        if abs(self.current_position) > 1e-7:
            unrealized_pnl_atr = (close - self.entry_price) * self.current_position / atr
            bars_in_trade_norm = min(1.0, self.bars_in_trade / 50.0)
        else:
            unrealized_pnl_atr = 0.0
            bars_in_trade_norm = 0.0

        pos_feats = np.array([
            self.current_position,
            np.clip(unrealized_pnl_atr, -5.0, 5.0),
            bars_in_trade_norm
        ], dtype=np.float32)

        return np.concatenate([market_feats, pos_feats])

    def step(self, action: int) -> Tuple[np.ndarray, float, bool, bool, Dict[str, Any]]:
        """
        Executes a transition:
        - Decision made on bar t close.
        - Filled at bar t+1 open.
        """
        assert self.action_space.contains(action), f"Invalid action: {action}"
        target_pos = ACTION_MAP[int(action)]
        old_pos = self.current_position

        # Enforce minimum holding period (if holding an active position, cannot change until min_holding_bars reached)
        if abs(old_pos) > 1e-7 and target_pos != old_pos:
            if self.bars_in_trade < self.config.min_holding_bars:
                target_pos = old_pos  # Suppress premature exit / flip

        # Market prices at bar t (decision) and bar t+1 (execution)
        curr_bar = self.df.iloc[self.current_step]
        next_bar = self.df.iloc[self.current_step + 1]

        c_t = float(curr_bar["close"])
        o_next = float(next_bar["open"])
        c_next = float(next_bar["close"])
        atr_t = float(curr_bar["atr_14"])

        # ── Return and Cost Calculation ───────────────────────────────────────
        if target_pos == old_pos:
            # Position maintained throughout bar t -> t+1
            cost_rate = 0.0
            cost_usd = 0.0
            r_step = old_pos * np.log(c_next / c_t)
            if abs(old_pos) > 1e-7:
                self.bars_in_trade += 1
            else:
                self.bars_in_trade = 0
        else:
            # Position transition fills at O_{t+1}
            cost_res = self.cost_model.calculate_cost(
                price=o_next,
                atr=atr_t,
                current_pos=old_pos,
                target_pos=target_pos,
                is_taker=True,
                notional_usd=self.config.notional_usd
            )
            cost_rate = cost_res.total_cost_rate
            cost_usd = cost_res.total_cost_usd
            self.total_costs_usd += cost_usd
            self.trade_count += 1

            # Old position held from C_t to O_{t+1}
            r_gap = old_pos * np.log(o_next / c_t)
            # New position held from O_{t+1} to C_{t+1}
            r_bar = target_pos * np.log(c_next / o_next)
            r_step = r_gap + r_bar

            # Update position state
            self.current_position = target_pos
            self.entry_price = o_next if abs(target_pos) > 1e-7 else 0.0
            self.bars_in_trade = 1 if abs(target_pos) > 1e-7 else 0

        # Update equity
        net_ret = r_step - cost_rate
        self.equity *= np.exp(net_ret)
        self.peak_equity = max(self.peak_equity, self.equity)

        # Drawdown and turnover penalties
        drawdown = max(0.0, (self.peak_equity - self.equity) / self.peak_equity)
        dd_penalty = self.config.drawdown_penalty_weight * drawdown
        turnover_penalty = self.config.turnover_penalty_weight * abs(target_pos - old_pos)

        # Reward = net return minus penalties
        reward = float(r_step - cost_rate - dd_penalty - turnover_penalty)

        # Advance step
        self.current_step += 1
        terminated = (self.current_step >= self.max_steps)
        truncated = (self.equity <= self.config.initial_equity * 0.5)  # 50% loss circuit breaker

        obs = self._get_observation()
        info = {
            "step": self.current_step,
            "equity": self.equity,
            "drawdown": drawdown,
            "position": self.current_position,
            "r_step": r_step,
            "cost_rate": cost_rate,
            "trade_count": self.trade_count
        }

        return obs, reward, terminated, truncated, info
