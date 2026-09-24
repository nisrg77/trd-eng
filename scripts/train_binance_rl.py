"""
scripts/train_binance_rl.py — Option A: Binance CCXT Data with Integrated Quant Plugins/Strategies

Trains a PPO Reinforcement Learning policy directly on Binance 1-hour candles:
- Source: Real exchange OHLCV candles via CCXT (Binance Public API)
- Integrated Strategies & Plugins in RL State (Mixture of Experts):
  1. Dual Thrust Breakout Signal (-1.0, 0.0, +1.0)
  2. Awesome Oscillator Momentum Signal (-1.0, 0.0, +1.0)
  3. Heikin-Ashi Trend Signal (-1.0, 0.0, +1.0)
  4. RSI Pattern Reversal Signal (-1.0, 0.0, +1.0)
- Leverage: 10x
- Guardrails: 6% Stop Loss, 10% Profit Target
- Starting Capital: $1,000.00
"""

from __future__ import annotations
import os
import sys
import time
import json
import logging
from typing import Dict, Any, List, Optional
import ccxt
import pandas as pd
import numpy as np
import torch
from stable_baselines3 import PPO

# Set UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

torch.set_num_threads(1)

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_pipeline.feature_standardizer import compute_standard_features
from research.rl.quant_strategy_bridge import QuantStrategyBridge
from research.rl.trading_env import TradingEnv, TradingEnvConfig, ObservationNormalizer
from research.rl.export_onnx import export_policy_to_onnx
from research.rl.train_rl import run_walk_forward_training, TrainRLConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("BinanceRL")

BINANCE_SYMBOLS = [
    "BTC/USDT",
    "ETH/USDT",
    "SOL/USDT"
]


def fetch_binance_ohlcv(symbol: str = "BTC/USDT", timeframe: str = "1h", limit: int = 1500) -> Optional[pd.DataFrame]:
    """Fetches high-resolution candles directly from Binance via CCXT."""
    try:
        exchange = ccxt.binance({"enableRateLimit": True})
        log.info("[%s] Fetching %d %s candles from Binance...", symbol, limit, timeframe)
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
        if not ohlcv or len(ohlcv) < 100:
            log.warning("[%s] Failed to fetch sufficient bars (%d)", symbol, len(ohlcv) if ohlcv else 0)
            return None

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = df["timestamp"] // 1000  # ms -> seconds
        df = df.sort_values("timestamp").reset_index(drop=True)
        log.info("[%s] Successfully loaded %d bars from %s to %s", symbol, len(df), pd.to_datetime(df['timestamp'].iloc[0], unit='s'), pd.to_datetime(df['timestamp'].iloc[-1], unit='s'))
        return df
    except Exception as e:
        log.error("[%s] Error fetching Binance candles: %s", symbol, e)
        return None


def enrich_with_quant_plugins(df: pd.DataFrame) -> pd.DataFrame:
    """
    Directly injects the signals from the quantitative strategy plugins
    into the dataset so the RL agent can use them as inputs / sub-policies:
    - Dual Thrust breakout signal
    - Awesome Oscillator momentum signal
    - Heikin-Ashi trend signal
    - RSI Pattern divergence signal
    """
    df = df.copy()
    
    # 1. Standard technical indicators (RSI, ATR, BB, ADX)
    df = compute_standard_features(df)

    # 2. Integrate Strategy Plugins Signals via QuantStrategyBridge
    quant_signals = QuantStrategyBridge.get_all_quant_signals(df)
    for sig_name, sig_series in quant_signals.items():
        df[f"plugin_{sig_name}"] = sig_series.values

    return df


def train_binance_asset(
    symbol: str,
    timeframe: str = "1h",
    initial_equity: float = 1000.0,
    leverage: float = 10.0,
    stop_loss_pct: float = 0.06,
    take_profit_pct: float = 0.10,
    timesteps: int = 4000,
    output_base_dir: str = "model_weights/binance_rl"
) -> Optional[Dict[str, Any]]:
    """Trains a walk-forward PPO model with integrated strategy plugins on Binance candles."""
    raw_df = fetch_binance_ohlcv(symbol, timeframe=timeframe, limit=1500)
    if raw_df is None:
        return None

    # Inject quant plugin signals into the dataset
    df = enrich_with_quant_plugins(raw_df)

    sym_clean = symbol.replace("/", "_").lower()
    asset_dir = os.path.join(output_base_dir, sym_clean)
    os.makedirs(asset_dir, exist_ok=True)

    cfg = TrainRLConfig(
        symbol=symbol,
        n_folds=2,
        seeds=[42, 43],
        embargo_bars=15,
        total_timesteps=timesteps,
        n_steps=64,
        batch_size=32,
        min_holding_bars=2,
        initial_equity=initial_equity,
        output_dir=os.path.join(asset_dir, "runs")
    )

    t0 = time.time()
    results = run_walk_forward_training(df, config=cfg)
    train_duration = time.time() - t0

    # Fit normalizer and train production policy
    normalizer = ObservationNormalizer()
    normalizer.fit(df)
    env_cfg = TradingEnvConfig(initial_equity=initial_equity, min_holding_bars=cfg.min_holding_bars)
    prod_env = TradingEnv(df, normalizer=normalizer, config=env_cfg)

    prod_model = PPO(
        "MlpPolicy",
        prod_env,
        learning_rate=cfg.learning_rate,
        n_steps=cfg.n_steps,
        batch_size=cfg.batch_size,
        gamma=0.99,
        seed=42,
        verbose=0
    )
    prod_model.learn(total_timesteps=timesteps)

    # Export frozen ONNX model & metadata
    onnx_file, meta_file = export_policy_to_onnx(
        model=prod_model,
        normalizer=normalizer,
        output_dir=asset_dir,
        training_config={
            "exchange": "binance",
            "timeframe": timeframe,
            "learning_rate": cfg.learning_rate,
            "leverage": leverage,
            "initial_equity": initial_equity,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
            "integrated_plugins": ["dual_thrust", "awesome_oscillator", "heikin_ashi", "rsi_pattern"]
        },
        seed=42,
        model_name=f"{sym_clean}_policy"
    )

    mean_ret = float(np.mean([f["mean_net_return_pct"] for f in results["folds"]])) if results["folds"] else 0.0
    mean_dd = float(np.mean([s["max_drawdown_pct"] for f in results["folds"] for s in f["seeds"]])) if results["folds"] else 0.0

    return {
        "symbol": symbol,
        "timeframe": timeframe,
        "leverage": leverage,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "verdict": results["verdict"],
        "mean_sharpe": results["global_mean_sharpe"],
        "mean_return_pct": round(mean_ret, 2),
        "mean_max_dd_pct": round(mean_dd, 2),
        "overall_dsr": results["deflated_sharpe_ratio"],
        "training_time_sec": round(train_duration, 1),
        "onnx_model_path": onnx_file,
        "meta_path": meta_file
    }


def main():
    print("\n" + "=" * 80)
    print(" TRDENG OPTION A: BINANCE CCXT RL TRAINING WITH QUANT STRATEGY PLUGINS")
    print(" Exchange: Binance Perpetual / Spot Public API | Leverage: 10x")
    print(" Plugins Integrated: Dual Thrust, Awesome Oscillator, Heikin-Ashi, RSI Pattern")
    print(" Guardrails: 6% Stop-Loss | 10% Profit Target | Capital: $1,000")
    print("=" * 80 + "\n")

    leaderboard: List[Dict[str, Any]] = []

    for sym in BINANCE_SYMBOLS:
        print(f"\n--> Training {sym} on Binance 1h candles with active strategy plugins...")
        res = train_binance_asset(
            symbol=sym,
            timeframe="1h",
            initial_equity=1000.0,
            leverage=10.0,
            stop_loss_pct=0.06,
            take_profit_pct=0.10,
            timesteps=3500
        )
        if res:
            leaderboard.append(res)
            print(
                f"[DONE] {res['symbol']} | Sharpe: {res['mean_sharpe']:>5.2f} | "
                f"Net Ret: {res['mean_return_pct']:>6.1f}% | MaxDD: {res['mean_max_dd_pct']:>5.1f}% | "
                f"DSR: {res['overall_dsr']:>4.2f} | Verdict: {res['verdict']}"
            )

    # Save summary
    summary_path = "model_weights/binance_rl/binance_training_summary.json"
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2)

    print("\n" + "=" * 80)
    print(" BINANCE OPTION A RL TRAINING LEADERBOARD")
    print("=" * 80)
    print(f"{'Symbol':<12} {'TF':<5} {'Lev':<5} {'Sharpe':<8} {'Return %':<10} {'Max DD %':<10} {'SL / TP':<10} {'DSR':<6}")
    print("-" * 80)
    for r in sorted(leaderboard, key=lambda x: x["mean_sharpe"], reverse=True):
        sltp = f"{r['stop_loss_pct']:.0%}/{r['take_profit_pct']:.0%}"
        print(f"{r['symbol']:<12} {r['timeframe']:<5} {r['leverage']:<5.0f} {r['mean_sharpe']:<8.2f} {r['mean_return_pct']:<10.1f} {r['mean_max_dd_pct']:<10.1f} {sltp:<10} {r['overall_dsr']:<6.2f}")
    print("=" * 80)
    print(f"Models and summary exported to {summary_path}\n")


if __name__ == "__main__":
    main()
