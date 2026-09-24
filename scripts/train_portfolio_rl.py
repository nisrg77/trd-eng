"""
scripts/train_portfolio_rl.py — High-Performance Parallel Multi-Asset RL Training Orchestrator

Targets:
- 3 Crypto Futures: BTC-USD, ETH-USD, SOL-USD (10x Leverage)
- Top 10 US Equities: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, AVGO, LLY, JPM (5x Leverage)
Guardrails:
- Max Loss Stop-Loss: 6% (0.06)
- Profit Target: 10% (0.10)
- Capital: $1,000 starting equity
- Execution: Multi-threaded parallel training across workers.
"""

from __future__ import annotations
import os
import sys
import time
import json
import logging
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Dict, Any, List, Optional, Tuple
import pandas as pd
import numpy as np
import yfinance as yf

if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from research.rl.train_rl import run_walk_forward_training, TrainRLConfig
from research.rl.export_onnx import export_policy_to_onnx
from research.rl.trading_env import TradingEnv, TradingEnvConfig, ObservationNormalizer
from stable_baselines3 import PPO
import torch

# Prevent CPU thread over-subscription during parallel execution
torch.set_num_threads(1)

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("PortfolioRL")

# Target Universe
CRYPTO_FUTURES = [
    "BTC-USD",
    "ETH-USD",
    "SOL-USD"
]

TOP_10_US_STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "LLY", "JPM"
]


def fetch_symbol_data(symbol: str, period: str = "2y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Downloads clean OHLCV candle data via Yahoo Finance."""
    try:
        raw_df = yf.download(symbol, period=period, interval=interval, progress=False)
        if raw_df.empty or len(raw_df) < 100:
            log.warning("[%s] Insufficient data returned (%d rows)", symbol, len(raw_df))
            return None

        raw_df = raw_df.reset_index()
        raw_df.columns = [str(c[0] if isinstance(c, tuple) else c).lower() for c in raw_df.columns]
        
        # Find timestamp/date column
        date_col = next((c for c in raw_df.columns if c in ["date", "datetime", "timestamp", "index"]), raw_df.columns[0])

        raw_df["timestamp"] = pd.to_datetime(raw_df[date_col]).astype("int64") // 10**9

        req_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        clean_df = raw_df[req_cols].dropna().sort_values("timestamp").reset_index(drop=True)
        return clean_df

    except Exception as e:
        log.error("[%s] Error downloading data: %s", symbol, e)
        return None


def train_single_asset(
    symbol: str,
    asset_class: str,
    df: pd.DataFrame,
    initial_equity: float = 1000.0,
    leverage: float = 10.0,
    stop_loss_pct: float = 0.06,
    take_profit_pct: float = 0.10,
    timesteps: int = 1500,
    output_base_dir: str = "model_weights/portfolio_rl"
) -> Dict[str, Any]:
    """Trains walk-forward PPO for a single asset and exports frozen ONNX model."""
    os.makedirs(output_base_dir, exist_ok=True)
    symbol_clean = symbol.replace("-", "_").replace("/", "_").lower()
    asset_dir = os.path.join(output_base_dir, symbol_clean)
    os.makedirs(asset_dir, exist_ok=True)

    cfg = TrainRLConfig(
        symbol=symbol,
        n_folds=2,
        seeds=[42, 43],
        embargo_bars=10,
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

    # Train final deployment model on the normalized dataset
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

    # Export to ONNX
    onnx_file, meta_file = export_policy_to_onnx(
        model=prod_model,
        normalizer=normalizer,
        output_dir=asset_dir,
        training_config={
            "learning_rate": cfg.learning_rate,
            "leverage": leverage,
            "initial_equity": initial_equity,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct
        },
        seed=42,
        model_name=f"{symbol_clean}_policy"
    )

    mean_ret = float(np.mean([f["mean_net_return_pct"] for f in results["folds"]])) if results["folds"] else 0.0
    mean_dd = float(np.mean([s["max_drawdown_pct"] for f in results["folds"] for s in f["seeds"]])) if results["folds"] else 0.0

    return {
        "symbol": symbol,
        "asset_class": asset_class,
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


def process_task(task_spec: Tuple[str, str, float, float, float, int]) -> Optional[Dict[str, Any]]:
    """Worker task for parallel training."""
    sym, asset_class, lev, sl, tp, steps = task_spec
    try:
        df = fetch_symbol_data(sym, period="2y", interval="1d")
        if df is None:
            return None
        res = train_single_asset(
            symbol=sym,
            asset_class=asset_class,
            df=df,
            initial_equity=1000.0,
            leverage=lev,
            stop_loss_pct=sl,
            take_profit_pct=tp,
            timesteps=steps
        )
        return res
    except Exception as e:
        log.error("Error training %s: %s", sym, e)
        return None


def main():
    print("\n" + "=" * 80)
    print(" TRDENG PORTFOLIO REINFORCEMENT LEARNING PARALLEL TRAINING")
    print(" Target: 3 Crypto Futures (10x Lev) + Top 10 US Equities (5x Lev)")
    print(" Guardrails: 6% Max Loss Stop-Loss | 10% Profit Target | Starting Capital: $1,000")
    print("=" * 80 + "\n")

    tasks = []
    # 3 Crypto futures (10x leverage, 6% SL, 10% TP)
    for sym in CRYPTO_FUTURES:
        tasks.append((sym, "crypto_futures", 10.0, 0.06, 0.10, 1500))

    # Top 10 US Equities (5x leverage, 6% SL, 10% TP)
    for sym in TOP_10_US_STOCKS:
        tasks.append((sym, "us_equity", 5.0, 0.06, 0.10, 1500))

    total = len(tasks)
    print(f"--> Launching parallel multi-threaded training across {total} assets (2 parallel workers)...")

    leaderboard: List[Dict[str, Any]] = []
    t_start = time.time()

    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {executor.submit(process_task, task): task[0] for task in tasks}
        completed = 0
        for fut in as_completed(future_map):
            completed += 1
            sym = future_map[fut]
            res = fut.result()
            if res:
                leaderboard.append(res)
                print(
                    f"[{completed:02d}/{total}] {res['symbol']:<8} ({res['asset_class']:<14} | {res['leverage']:>2.0f}x) | "
                    f"Sharpe: {res['mean_sharpe']:>5.2f} | Ret: {res['mean_return_pct']:>6.1f}% | "
                    f"MaxDD: {res['mean_max_dd_pct']:>5.1f}% | DSR: {res['overall_dsr']:>4.2f} | "
                    f"SL: {res['stop_loss_pct']:.0%} | TP: {res['take_profit_pct']:.0%}"
                )

    total_time = time.time() - t_start

    # Output Portfolio Leaderboard
    summary_file = "model_weights/portfolio_rl/portfolio_training_summary.json"
    os.makedirs(os.path.dirname(summary_file), exist_ok=True)
    with open(summary_file, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2)

    print("\n" + "=" * 80)
    print(f" PORTFOLIO TRAINING SUMMARY LEADERBOARD ({len(leaderboard)} Models Trained in {total_time:.1f}s)")
    print("=" * 80)
    print(f"{'Symbol':<10} {'Class':<15} {'Lev':<5} {'Sharpe':<8} {'Return %':<10} {'Max DD %':<10} {'SL / TP':<10} {'DSR':<6}")
    print("-" * 80)
    for r in sorted(leaderboard, key=lambda x: x["mean_sharpe"], reverse=True):
        sltp = f"{r['stop_loss_pct']:.0%}/{r['take_profit_pct']:.0%}"
        print(f"{r['symbol']:<10} {r['asset_class']:<15} {r['leverage']:<5.0f} {r['mean_sharpe']:<8.2f} {r['mean_return_pct']:<10.1f} {r['mean_max_dd_pct']:<10.1f} {sltp:<10} {r['overall_dsr']:<6.2f}")
    print("=" * 80)
    print(f"Saved complete summary and ONNX models to {summary_file}\n")


if __name__ == "__main__":
    main()
