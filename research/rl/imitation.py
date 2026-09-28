"""
research/rl/imitation.py — Behavior Cloning Warm Start & MaxEnt IRL Diagnostic

Implements:
1. Multi-Strategy Consensus Extraction:
   Aggregates votes across the 4 QuantStrategyBridge signals (Dual Thrust,
   Awesome Oscillator, Heikin-Ashi, RSI Pattern) requiring agreement >= 3.
2. MaxEnt Inverse Reinforcement Learning (IRL):
   Recovers implicit objective weights theta:
   - return
   - drawdown penalty
   - turnover penalty
   - holding duration penalty
3. IRL Reward Function:
   R_t = theta_return * LogRet - theta_drawdown * MaxDD_Step - theta_turnover * Churn - theta_holding * DurationPenalty
   Preserves invariant: Flat policy earns strictly 0.0.
4. Behavior Cloning (BC) Warm Start:
   Pre-trains PPO Actor network weights via Cross-Entropy Loss on consensus
   actions before live paper exploration.
"""

from __future__ import annotations
import math
import logging
from typing import Dict, Any, List, Optional, Tuple, Callable

import numpy as np
import pandas as pd
import torch
import torch.nn as nn
import torch.optim as optim
from torch.utils.data import TensorDataset, DataLoader
from stable_baselines3 import PPO

from research.rl.quant_strategy_bridge import QuantStrategyBridge
from research.rl.trading_env import (
    TradingEnv,
    ObservationNormalizer,
    prepare_market_features,
    MARKET_FEATURE_NAMES,
    POSITION_FEATURE_NAMES
)

log = logging.getLogger(__name__)


def extract_expert_demonstrations(
    df: pd.DataFrame,
    normalizer: Optional[ObservationNormalizer] = None,
    consensus_threshold: int = 3
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Identifies bars where at least `consensus_threshold` of the 4 QuantStrategyBridge signals agree.
    Maps agreed direction {-1: Short -> action 0, 0: Flat -> action 1, +1: Long -> action 2}.
    Returns:
        (observations_matrix [N, 20], expert_actions_vector [N])
    """
    signals = QuantStrategyBridge.get_all_quant_signals(df)
    sig_df = pd.DataFrame(signals)

    # Direction quantization
    pos_votes = (sig_df > 0.5).sum(axis=1)
    neg_votes = (sig_df < -0.5).sum(axis=1)
    flat_votes = (sig_df.abs() <= 0.5).sum(axis=1)

    expert_actions = []
    valid_indices = []

    for idx in range(len(df)):
        if pos_votes.iloc[idx] >= consensus_threshold:
            expert_actions.append(2)  # Long
            valid_indices.append(idx)
        elif neg_votes.iloc[idx] >= consensus_threshold:
            expert_actions.append(0)  # Short
            valid_indices.append(idx)
        elif flat_votes.iloc[idx] >= consensus_threshold:
            expert_actions.append(1)  # Flat
            valid_indices.append(idx)

    if not valid_indices:
        log.warning("[Imitation] No bars met consensus threshold %d", consensus_threshold)
        return np.empty((0, 20), dtype=np.float32), np.empty((0,), dtype=np.int64)

    # Build 20-dim observations
    feats_df = prepare_market_features(df)
    norm = normalizer or ObservationNormalizer()
    if not norm.stats:
        norm.fit(feats_df)

    obs_list = []
    for idx in valid_indices:
        row = feats_df.iloc[idx]
        mkt_feats = norm.normalize_market_features(row)
        # Baseline context when evaluating signal in isolation: flat position
        pos_feats = np.array([0.0, 0.0, 0.0], dtype=np.float32)
        obs_vec = np.concatenate([mkt_feats, pos_feats])
        obs_list.append(obs_vec)

    obs_arr = np.array(obs_list, dtype=np.float32)
    act_arr = np.array(expert_actions, dtype=np.int64)
    log.info(
        "[Imitation] Extracted %d expert demonstrations (consensus >= %d, dim=%d)",
        len(act_arr), consensus_threshold, obs_arr.shape[1]
    )
    return obs_arr, act_arr


class IRLRewardFunction:
    """
    Composite reward function constructed from recovered MaxEnt IRL weights:
    R_t = theta_return * LogRet - theta_drawdown * MaxDD_Step - theta_turnover * Churn - theta_holding * DurationPenalty
    """

    def __init__(
        self,
        theta_return: float = 0.50,
        theta_drawdown: float = 0.25,
        theta_turnover: float = 0.15,
        theta_holding: float = 0.10
    ) -> None:
        self.theta_return = theta_return
        self.theta_drawdown = theta_drawdown
        self.theta_turnover = theta_turnover
        self.theta_holding = theta_holding

    @classmethod
    def from_weights_dict(cls, weights: Dict[str, float]) -> IRLRewardFunction:
        return cls(
            theta_return=abs(weights.get("return", 0.50)),
            theta_drawdown=abs(weights.get("drawdown", 0.25)),
            theta_turnover=abs(weights.get("turnover", 0.15)),
            theta_holding=abs(weights.get("holding_time", 0.10))
        )

    def __call__(self, metrics: Dict[str, Any]) -> float:
        """
        Evaluates step reward from transition metrics:
        metrics keys: r_step, cost_rate, drawdown, churn, bars_in_trade, current_pos, target_pos
        """
        curr_pos = metrics.get("current_pos", 0.0)
        target_pos = metrics.get("target_pos", 0.0)

        # Invariant: staying flat in cash yields strictly 0.0
        if abs(curr_pos) < 1e-7 and abs(target_pos) < 1e-7:
            return 0.0

        r_step = metrics.get("r_step", 0.0)
        cost_rate = metrics.get("cost_rate", 0.0)
        log_ret = r_step - cost_rate

        drawdown = metrics.get("drawdown", 0.0)
        max_dd_step = drawdown if abs(target_pos) > 1e-7 else 0.0

        churn = metrics.get("churn", 0.0)
        bars_in_trade = metrics.get("bars_in_trade", 0)
        duration_penalty = min(1.0, float(bars_in_trade) / 50.0) if bars_in_trade > 20 else 0.0

        reward = (
            self.theta_return * log_ret
            - self.theta_drawdown * max_dd_step
            - self.theta_turnover * churn
            - self.theta_holding * duration_penalty
        )
        return float(reward)


class MaxEntIRLDiagnostic:
    """
    Linear Maximum Entropy Inverse Reinforcement Learning diagnostic.
    Recovers implied weights theta for [return, drawdown, turnover, holding_time].
    """

    def __init__(self, feature_names: Optional[List[str]] = None, lr: float = 0.05) -> None:
        self.feature_names = feature_names or ["return", "drawdown", "turnover", "holding_time"]
        self.lr = lr
        self.weights = np.array([0.5, 0.25, 0.15, 0.10], dtype=np.float64)

    def extract_feature_expectations_from_actions(
        self,
        df: pd.DataFrame,
        actions: np.ndarray,
        cost_rate: float = 0.0006
    ) -> np.ndarray:
        """
        Computes empirical feature expectations mu = [return, drawdown, turnover, holding_time]
        given an action sequence over df.
        """
        close = df["close"].values
        n = min(len(actions), len(close) - 1)
        if n < 5:
            return np.array([0.0, 0.0, 0.0, 0.0], dtype=np.float64)

        action_map = {0: -1.0, 1: 0.0, 2: 1.0}
        positions = [action_map.get(int(a), 0.0) for a in actions[:n]]

        # Returns
        rets = np.log(close[1:n+1] / close[:n])
        strat_rets = np.array(positions) * rets
        turnover = np.sum(np.abs(np.diff([0.0] + positions))) / max(1, n)

        # Equity and Drawdown
        equity = np.cumprod(np.exp(strat_rets - turnover * cost_rate))
        peak = np.maximum.accumulate(equity)
        dd = (peak - equity) / peak
        avg_dd = float(np.mean(dd))

        # Holding duration
        bars_held = 0
        durations = []
        for p in positions:
            if abs(p) > 1e-7:
                bars_held += 1
            else:
                if bars_held > 0:
                    durations.append(bars_held)
                bars_held = 0
        if bars_held > 0:
            durations.append(bars_held)
        avg_duration_norm = float(np.mean(durations) / 50.0) if durations else 0.0

        cum_ret = float(np.sum(strat_rets))
        return np.array([cum_ret, avg_dd, turnover, avg_duration_norm], dtype=np.float64)

    def fit_from_trajectories(
        self,
        expert_feature_expectations: np.ndarray,
        baseline_feature_expectations: np.ndarray,
        iterations: int = 50
    ) -> Dict[str, float]:
        """
        Gradient update: theta <- theta + alpha * (mu_expert - mu_baseline)
        Regularizes via L2 weight decay (0.98 shrinkage).
        """
        w = np.copy(self.weights)
        for _ in range(iterations):
            grad = expert_feature_expectations - baseline_feature_expectations
            w += self.lr * grad
            w *= 0.98

        # Normalize weights so sum of absolute values equals 1.0
        norm = np.sum(np.abs(w)) + 1e-9
        normalized_weights = w / norm
        self.weights = normalized_weights

        result = {name: round(float(w_val), 4) for name, w_val in zip(self.feature_names, normalized_weights)}
        log.info("[MaxEntIRL] Recovered implied reward weights: %s", result)
        return result

    def fit_from_expert_and_env(
        self,
        df: pd.DataFrame,
        expert_actions: np.ndarray,
        iterations: int = 50
    ) -> Tuple[Dict[str, float], IRLRewardFunction]:
        """
        Extracts expert feature expectations, runs baseline random walk expectations,
        fits MaxEnt IRL weights, and returns the configured IRLRewardFunction.
        """
        expert_fe = self.extract_feature_expectations_from_actions(df, expert_actions)

        # Baseline random policy expectations
        np.random.seed(42)
        random_actions = np.random.choice([0, 1, 2], size=len(expert_actions))
        baseline_fe = self.extract_feature_expectations_from_actions(df, random_actions)

        weights = self.fit_from_trajectories(expert_fe, baseline_fe, iterations=iterations)
        reward_fn = IRLRewardFunction.from_weights_dict(weights)
        return weights, reward_fn


def warm_start_ppo_with_bc(
    model: PPO,
    observations: np.ndarray,
    actions: np.ndarray,
    epochs: int = 15,
    batch_size: int = 64,
    lr: float = 1e-3
) -> Dict[str, float]:
    """
    Supervised Behavior Cloning (BC) pre-training on actor network weights.
    Minimizes CrossEntropyLoss between policy action logits and expert demonstration actions.
    """
    if len(observations) == 0:
        return {"final_loss": 0.0, "accuracy": 0.0, "samples": 0}

    policy = model.policy
    device = policy.device
    obs_t = torch.as_tensor(observations, dtype=torch.float32, device=device)
    act_t = torch.as_tensor(actions, dtype=torch.long, device=device)

    dataset = TensorDataset(obs_t, act_t)
    loader = DataLoader(dataset, batch_size=batch_size, shuffle=True)

    # Optimize actor parameters only
    actor_params = list(policy.mlp_extractor.policy_net.parameters()) + list(policy.action_net.parameters())
    optimizer = optim.Adam(actor_params, lr=lr)
    criterion = nn.CrossEntropyLoss()

    policy.train()
    final_loss = 0.0
    for epoch in range(epochs):
        epoch_loss = 0.0
        correct = 0
        total = 0
        for batch_obs, batch_act in loader:
            optimizer.zero_grad()
            features = policy.extract_features(batch_obs)
            latent_pi = policy.mlp_extractor.forward_actor(features)
            logits = policy.action_net(latent_pi)

            loss = criterion(logits, batch_act)
            loss.backward()
            optimizer.step()

            epoch_loss += loss.item() * len(batch_act)
            preds = torch.argmax(logits, dim=1)
            correct += (preds == batch_act).sum().item()
            total += len(batch_act)

        final_loss = epoch_loss / max(1, total)

    accuracy = correct / max(1, total)
    log.info(
        "[Imitation] BC Warm Start completed: Loss=%.4f, Accuracy=%.2f%% (%d samples)",
        final_loss, accuracy * 100, total
    )
    return {
        "final_loss": round(final_loss, 4),
        "accuracy": round(accuracy, 4),
        "samples": total
    }
