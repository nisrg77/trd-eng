"""
scripts/train_stocks_rl.py — Option B: Top 10 US Stocks with Integrated Strategy Plugins

Trains PPO Reinforcement Learning policies on the Top 10 US Equities using Yahoo Finance data,
with direct integration of quantitative strategy plugins in the RL observation space:
- Target Universe: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, AVGO, LLY, JPM
- Integrated Strategy Plugins (Mixture of Experts):
  1. Dual Thrust Breakout Signal (-1.0, 0.0, +1.0)
  2. Awesome Oscillator Momentum Signal (-1.0, 0.0, +1.0)
  3. Heikin-Ashi Trend Signal (-1.0, 0.0, +1.0)
  4. RSI Pattern Divergence Signal (-1.0, 0.0, +1.0)
- Leverage: 5x
- Guardrails: 6% Max Loss Stop-Loss | 10% Profit Target
- Capital: $1,000.00
- Multi-threaded parallel training across workers
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
import torch
from stable_baselines3 import PPO

# Set UTF-8 encoding
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

# Limit intra-op threads to prevent CPU thread contention
torch.set_num_threads(1)

# Ensure project root is in sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from data_pipeline.feature_standardizer import compute_standard_features
from research.rl.quant_strategy_bridge import QuantStrategyBridge
from research.rl.native_strategies_bridge import NativeStrategiesBridge
from research.rl.trading_env import TradingEnv, TradingEnvConfig, ObservationNormalizer
from research.rl.export_onnx import export_policy_to_onnx
from research.rl.train_rl import run_walk_forward_training, TrainRLConfig

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("StocksRL")

TOP_10_US_STOCKS = [
    "AAPL", "MSFT", "NVDA", "AMZN", "GOOGL", "META", "TSLA", "AVGO", "LLY", "JPM"
]


def fetch_stock_data(symbol: str, period: str = "2y", interval: str = "1d") -> Optional[pd.DataFrame]:
    """Downloads clean OHLCV candle data via Yahoo Finance."""
    try:
        raw_df = yf.download(symbol, period=period, interval=interval, progress=False)
        if raw_df.empty or len(raw_df) < 100:
            log.warning("[%s] Insufficient data returned (%d rows)", symbol, len(raw_df))
            return None

        raw_df = raw_df.reset_index()
        raw_df.columns = [str(c[0] if isinstance(c, tuple) else c).lower() for c in raw_df.columns]
        
        date_col = next((c for c in raw_df.columns if c in ["date", "datetime", "timestamp", "index"]), raw_df.columns[0])
        raw_df["timestamp"] = pd.to_datetime(raw_df[date_col]).astype("int64") // 10**9

        req_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        clean_df = raw_df[req_cols].dropna().sort_values("timestamp").reset_index(drop=True)
        return clean_df

    except Exception as e:
        log.error("[%s] Error downloading data: %s", symbol, e)
        return None


def enrich_with_strategy_plugins(symbol: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    Directly injects the signals from BOTH quant math models AND native TRDENG strategies/
    into the observation space so the RL agent trains as a true Mixture of Experts:
    - Native strategies: Bollinger Pattern (W/M), Heikin-Ashi SAR, Dual Thrust, ORB, VPOC
    - Quant signals: Awesome Oscillator, RSI Pattern
    """
    df = df.copy()
    
    # 1. Standard technical indicators (RSI, ATR, BB, ADX)
    df = compute_standard_features(df)

    # 2. Integrate Strategy Plugins Signals via QuantStrategyBridge
    quant_signals = QuantStrategyBridge.get_all_quant_signals(df)
    for sig_name, sig_series in quant_signals.items():
        df[f"plugin_{sig_name}"] = sig_series.values

    # 3. Native TRDENG Strategy Plugins from strategies/ folder
    bridge = NativeStrategiesBridge(asset_class="stock")
    df = bridge.enrich_dataframe(symbol, df)

    return df


def train_single_stock(
    symbol: str,
    df: pd.DataFrame,
    initial_equity: float = 1000.0,
    leverage: float = 5.0,
    stop_loss_pct: float = 0.06,
    take_profit_pct: float = 0.10,
    timesteps: int = 2000,
    output_base_dir: str = "model_weights/stocks_rl"
) -> Dict[str, Any]:
    """Trains walk-forward PPO with strategy plugins and exports frozen ONNX model."""
    os.makedirs(output_base_dir, exist_ok=True)
    sym_clean = symbol.lower()
    asset_dir = os.path.join(output_base_dir, sym_clean)
    os.makedirs(asset_dir, exist_ok=True)

    # Inject BOTH native strategies and quant plugins into dataframe
    df = enrich_with_strategy_plugins(symbol, df)

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

    # Fit normalizer and train production policy on full dataset
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
            "source": "yahoo_finance",
            "learning_rate": cfg.learning_rate,
            "leverage": leverage,
            "initial_equity": initial_equity,
            "stop_loss_pct": stop_loss_pct,
            "integrated_plugins": [
                "strat_bb_pattern",
                "strat_ha_sar",
                "strat_dual_thrust",
                "strat_orb_breakout",
                "strat_vpoc_reversion",
                "strat_nfi_momentum",
                "plugin_dual_thrust_dir",
                "plugin_awesome_osc",
                "plugin_heikin_ashi_trend",
                "plugin_rsi_pattern",
            ]
        },
        seed=42,
        model_name=f"{sym_clean}_policy"
    )

    mean_ret = float(np.mean([f["mean_net_return_pct"] for f in results["folds"]])) if results["folds"] else 0.0
    mean_dd = float(np.mean([s["max_drawdown_pct"] for f in results["folds"] for s in f["seeds"]])) if results["folds"] else 0.0

    return {
        "symbol": symbol,
        "asset_class": "us_equity",
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


def process_stock(sym: str) -> Optional[Dict[str, Any]]:
    """Worker task for parallel stock training."""
    try:
        df = fetch_stock_data(sym, period="2y", interval="1d")
        if df is None:
            return None
        res = train_single_stock(
            symbol=sym,
            df=df,
            initial_equity=1000.0,
            leverage=5.0,
            stop_loss_pct=0.06,
            take_profit_pct=0.10,
            timesteps=2000
        )
        return res
    except Exception as e:
        log.error("Error processing %s: %s", sym, e)
        return None


def main():
    print("\n" + "=" * 80)
    print(" TRDENG OPTION B: TOP 10 US STOCKS RL WITH NATIVE STRATEGIES & QUANT PLUGINS")
    print(" Universe: AAPL, MSFT, NVDA, AMZN, GOOGL, META, TSLA, AVGO, LLY, JPM")
    print(" Plugins: BB Pattern, HA SAR, Dual Thrust, ORB, VPOC, NFI + AO, RSI Divergence")
    print(" Leverage: 5x | Guardrails: 6% Stop-Loss, 10% Profit Target | Capital: $1,000")
    print("=" * 80 + "\n")

    leaderboard: List[Dict[str, Any]] = []
    t_start = time.time()
    total = len(TOP_10_US_STOCKS)

    print(f"--> Launching parallel training across {total} stocks (2 parallel workers)...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {executor.submit(process_stock, sym): sym for sym in TOP_10_US_STOCKS}
        completed = 0
        for fut in as_completed(future_map):
            completed += 1
            sym = future_map[fut]
            res = fut.result()
            if res:
                leaderboard.append(res)
                print(
                    f"[{completed:02d}/{total}] {res['symbol']:<6} | "
                    f"Sharpe: {res['mean_sharpe']:>5.2f} | Net Ret: {res['mean_return_pct']:>6.1f}% | "
                    f"MaxDD: {res['mean_max_dd_pct']:>5.1f}% | DSR: {res['overall_dsr']:>4.2f} | "
                    f"SL: {res['stop_loss_pct']:.0%} | TP: {res['take_profit_pct']:.0%}"
                )

    total_time = time.time() - t_start

    # Save summary
    summary_path = "model_weights/stocks_rl/stocks_training_summary.json"
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2)

    print("\n" + "=" * 80)
    print(f" TOP 10 US STOCKS RL TRAINING SUMMARY ({len(leaderboard)} Models in {total_time:.1f}s)")
    print("=" * 80)
    print(f"{'Symbol':<8} {'Lev':<5} {'Sharpe':<8} {'Return %':<10} {'Max DD %':<10} {'SL / TP':<10} {'DSR':<6} {'Verdict':<8}")
    print("-" * 80)
    for r in sorted(leaderboard, key=lambda x: x["mean_sharpe"], reverse=True):
        sltp = f"{r['stop_loss_pct']:.0%}/{r['take_profit_pct']:.0%}"
        print(f"{r['symbol']:<8} {r['leverage']:<5.0f} {r['mean_sharpe']:<8.2f} {r['mean_return_pct']:<10.1f} {r['mean_max_dd_pct']:<10.1f} {sltp:<10} {r['overall_dsr']:<6.2f} {r['verdict']:<8}")
    print("=" * 80)
    print(f"Exported models and summary to {summary_path}\n")


if __name__ == "__main__":
    main()
