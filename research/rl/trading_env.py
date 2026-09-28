"""
research/rl/trading_env.py — Cost-Aware Gymnasium Trading Environment (20-Dim)

Strictly causal, no-lookahead RL environment for offline and paper training:
1. Observation Space (20-dim Box bounded [-5.0, 5.0]):
   - Base Causal Market Features (9-dim): log returns (lags 1, 3, 5, 12), RSI-14 centered,
     ATR-distance to BB, BB width, ADX-14 centered, 20-bar realized vol.
   - Microstructure & Sentiment Features (8-dim): OFI, normalized spread, queue depletion
     velocity, VPIN, CVD / 20-bar volume, block trade density, event polarity shift,
     volatility anticipation index.
   - Position & Context Features (3-dim): current position, unrealized PnL in ATR units,
     normalized bars in trade.
   - Standardized via ObservationNormalizer fit strictly on TRAIN split.
2. Action Space (Discrete(3)):
   - 0 = Short (-1.0), 1 = Flat (0.0), 2 = Long (+1.0).
   - Enforces configurable min_holding_bars to prevent churn.
3. Execution Timing (Zero Lookahead):
   - Decision made at bar t close; fill executed at bar t+1 open.
4. Transaction Costs:
   - Evaluated via execution/cost_model.py (taker fee, spread, ATR slippage).
5. Reward Formulation:
   - Supports pluggable IRL reward functions (IRLRewardFunction) or default
     cost-penalized, drawdown-penalized return.
   - Invariant: Flat policy yields reward exactly 0.0.
"""

from __future__ import annotations
import os
import json
import math
import logging
from dataclasses import dataclass, field
from typing import Dict, Any, Optional, Tuple, List, Callable

import numpy as np
import pandas as pd
import gymnasium as gym
from gymnasium import spaces

from data_pipeline.feature_standardizer import compute_standard_features
from execution.cost_model import CostModel, CostModelConfig, cost_model
from research.rl.features import (
    MICROSTRUCTURE_FEATURE_NAMES,
    MicrostructureFeatureExtractor
)

log = logging.getLogger(__name__)

BASE_MARKET_FEATURE_NAMES = [
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

POSITION_FEATURE_NAMES = [
    "current_position",
    "unrealized_pnl_atr",
    "bars_in_trade_norm"
]

MARKET_FEATURE_NAMES = list(BASE_MARKET_FEATURE_NAMES) + list(MICROSTRUCTURE_FEATURE_NAMES)
ALL_FEATURE_NAMES = list(MARKET_FEATURE_NAMES) + list(POSITION_FEATURE_NAMES)

ACTION_MAP = {
    0: -1.0,  # SHORT
    1: 0.0,   # FLAT
    2: 1.0    # LONG
}


class ObservationNormalizer:
    """
    Fits feature standardization (mean, std) on the training split only,
    supporting dynamic strategy/plugin features, and serializes/deserializes stats to disk.
    Clips all normalized values to [-5.0, 5.0].
    """

    def __init__(
        self,
        stats: Optional[Dict[str, Dict[str, float]]] = None,
        feature_names: Optional[List[str]] = None
    ) -> None:
        self.stats = stats or {}
        self.feature_names = feature_names or list(MARKET_FEATURE_NAMES)

    def fit(self, df: pd.DataFrame, extra_features: Optional[List[str]] = None) -> None:
        """
        Computes mean and std for base + microstructure market features plus any extra strategy/plugin features.
        Automatically detects all columns starting with 'strat_' or 'plugin_' if not provided.
        """
        self.stats = {}
        feature_list = list(MARKET_FEATURE_NAMES)
        if extra_features is not None:
            detected_extras = extra_features
        else:
            detected_extras = [
                c for c in df.columns 
                if (c.startswith("strat_") or c.startswith("plugin_")) and c not in feature_list
            ]
        
        for col in detected_extras:
            if col not in feature_list:
                feature_list.append(col)
                
        self.feature_names = feature_list

        for col in self.feature_names:
            if col in df.columns:
                # For discrete/bounded strategy signals (-1.0, 0.0, 1.0), preserve directional semantics
                if col.startswith("strat_") or col.startswith("plugin_"):
                    self.stats[col] = {
                        "mean": 0.0,
                        "std": 1.0
                    }
                else:
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
        """Transforms a single bar's market features using fitted stats, clipped to [-5.0, 5.0]."""
        norm_vals = []
        for col in self.feature_names:
            raw_val = float(row.get(col, 0.0))
            stat = self.stats.get(col, {"mean": 0.0, "std": 1.0})
            norm = (raw_val - stat["mean"]) / stat["std"]
            norm_vals.append(np.clip(norm, -5.0, 5.0))
        return np.array(norm_vals, dtype=np.float32)

    def save(self, filepath: str) -> None:
        os.makedirs(os.path.dirname(os.path.abspath(filepath)), exist_ok=True)
        payload = {
            "stats": self.stats,
            "feature_names": self.feature_names
        }
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2)

    @classmethod
    def load(cls, filepath: str) -> ObservationNormalizer:
        with open(filepath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict) and "stats" in data and "feature_names" in data:
            return cls(stats=data["stats"], feature_names=data["feature_names"])
        elif isinstance(data, dict):
            return cls(stats=data, feature_names=list(data.keys()))
        return cls()


def prepare_market_features(df: pd.DataFrame) -> pd.DataFrame:
    """
    Computes standard causal features, log-return lags, and 8 microstructure
    dimensions on OHLCV data, preserving any pre-injected strategy/plugin signals.
    """
    plugin_cols = {c: df[c].values for c in df.columns if c.startswith("strat_") or c.startswith("plugin_")}
    out = compute_standard_features(df)
    for c, arr in plugin_cols.items():
        out[c] = arr
    close = out["close"].astype(np.float64)

    # 1. Log Returns over multiple lags
    out["log_ret_1"] = np.log(close / close.shift(1).clip(lower=1e-6)).fillna(0.0)
    out["log_ret_3"] = np.log(close / close.shift(3).clip(lower=1e-6)).fillna(0.0)
    out["log_ret_5"] = np.log(close / close.shift(5).clip(lower=1e-6)).fillna(0.0)
    out["log_ret_12"] = np.log(close / close.shift(12).clip(lower=1e-6)).fillna(0.0)

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

    # 6. Microstructure, Order Book, Institutional & Sentiment Features
    out = MicrostructureFeatureExtractor.compute_features_df(out)

    return out


@dataclass
class TradingEnvConfig:
    initial_equity: float = 1000.0
    min_holding_bars: int = 5
    drawdown_penalty_weight: float = 0.1
    turnover_penalty_weight: float = 0.001
    holding_penalty_weight: float = 0.0005
    cost_config: CostModelConfig = field(default_factory=CostModelConfig)
    notional_usd: float = 1000.0
    reward_fn: Optional[Callable[[Dict[str, Any]], float]] = None
    target_return_pct: float = 7.0  # 7% for crypto, 4% for US stocks
    max_leverage: float = 30.0
    max_daily_trades: int = 20

class TradingEnv(gym.Env):
    """
    Cost-aware, zero-lookahead Gymnasium trading environment with 20-dim state space.
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

        # Precompute causal features (base + microstructure)
        self.df = prepare_market_features(df).reset_index(drop=True)
        self.normalizer = normalizer or ObservationNormalizer()
        if not self.normalizer.stats or not hasattr(self.normalizer, "feature_names") or not self.normalizer.feature_names:
            self.normalizer.fit(self.df)

        self.market_feature_names = list(self.normalizer.feature_names)
        self.all_feature_names = self.market_feature_names + list(POSITION_FEATURE_NAMES)

        # Define Gym spaces
        self.action_space = spaces.Discrete(3)  # 0: Short, 1: Flat, 2: Long
        self.observation_space = spaces.Box(
            low=-5.0,
            high=5.0,
            shape=(len(self.all_feature_names),),
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
        if self.current_step >= self.max_steps:
            self.current_step = max(0, self.max_steps - 5)

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
            "position": self.current_position,
            "trade_count": self.trade_count
        }
        return obs, info

    def _get_observation(self) -> np.ndarray:
        """
        Constructs normalized observation vector:
        [market_features (17), position_features (3)] -> 20 dims
        """
        row = self.df.iloc[self.current_step]
        market_feats = self.normalizer.normalize_market_features(row)

        curr_price = float(row["close"])
        atr = max(1e-6, float(row["atr_14"]))

        unrealized_pnl_atr = 0.0
        if abs(self.current_position) > 1e-7 and self.entry_price > 0:
            unrealized_pnl_atr = (curr_price - self.entry_price) * self.current_position / atr

        bars_in_trade_norm = min(1.0, float(self.bars_in_trade) / 50.0)

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

        # Enforce minimum holding period
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
            cost_rate = 0.0
            cost_usd = 0.0
            r_step = old_pos * np.log(c_next / c_t)
            if abs(old_pos) > 1e-7:
                self.bars_in_trade += 1
            else:
                self.bars_in_trade = 0
        else:
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

            r_gap = old_pos * np.log(o_next / c_t)
            r_bar = target_pos * np.log(c_next / o_next)
            r_step = r_gap + r_bar

            self.current_position = target_pos
            self.entry_price = o_next if abs(target_pos) > 1e-7 else 0.0
            self.bars_in_trade = 1 if abs(target_pos) > 1e-7 else 0

        # Update equity
        net_ret = r_step - cost_rate
        self.equity *= np.exp(net_ret)
        self.peak_equity = max(self.peak_equity, self.equity)

        # Drawdown and penalties
        drawdown = max(0.0, (self.peak_equity - self.equity) / self.peak_equity)
        dd_penalty = self.config.drawdown_penalty_weight * drawdown if abs(self.current_position) > 1e-7 else 0.0
        turnover_penalty = self.config.turnover_penalty_weight * abs(target_pos - old_pos)
        duration_penalty = self.config.holding_penalty_weight * (self.bars_in_trade / 50.0) if self.bars_in_trade > 20 else 0.0

        # Reward evaluation (pluggable reward_fn or default)
        if abs(old_pos) < 1e-7 and abs(target_pos) < 1e-7:
            # Absolute invariant: Flat policy earns exactly 0.0
            reward = 0.0
        elif self.config.reward_fn is not None:
            reward_metrics = {
                "r_step": r_step,
                "cost_rate": cost_rate,
                "drawdown": drawdown,
                "churn": abs(target_pos - old_pos),
                "bars_in_trade": self.bars_in_trade,
                "current_pos": old_pos,
                "target_pos": target_pos,
                "net_ret": net_ret
            }
            reward = float(self.config.reward_fn(reward_metrics))
        else:
            reward = float(r_step - cost_rate - dd_penalty - turnover_penalty - duration_penalty)

        # Advance step
        self.current_step += 1
        terminated = (self.current_step >= self.max_steps)
        truncated = (self.equity <= self.config.initial_equity * 0.5)

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
