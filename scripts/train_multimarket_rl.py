"""
scripts/train_multimarket_rl.py — High-Frequency Multi-Market RL with Full Strategy Plugins

Executes walk-forward PPO training with complete strategy plugin ingestion:
- Target Universe:
  1. Top 5 US Stocks: AAPL, MSFT, NVDA, AMZN, TSLA (1-Hour candles via Yahoo Finance)
  2. Top 2 Crypto: BTC/USDT, ETH/USDT (1-Hour candles via Binance CCXT)
- All 10 Integrated Strategy Plugins (Mixture of Experts):
  - Native Strategies: Bollinger Pattern, Heikin-Ashi SAR, Dual Thrust, ORB, VPOC, NFI
  - Quant Signals: Dual Thrust breakout, Awesome Oscillator, Heikin-Ashi trend, RSI divergence
- Leverage: 5x for US Stocks | 10x for Crypto
- Risk Guardrails: 6% Max Loss Stop-Loss | 10% Profit Target
- Initial Capital: $1,000.00
- Cash-Neutral Reward Formulation: Zero continuous drag when sitting in cash
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
import ccxt
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
log = logging.getLogger("MultiMarketRL")

TARGET_STOCKS = ["AAPL", "MSFT", "NVDA", "AMZN", "TSLA"]
TARGET_CRYPTO = ["BTC/USDT", "ETH/USDT"]


def fetch_stock_1h_data(symbol: str, bars_count: int = 1500) -> Optional[pd.DataFrame]:
    """Downloads clean 1-hour OHLCV candle data via Yahoo Finance."""
    try:
        raw_df = yf.download(symbol, period="730d", interval="1h", progress=False)
        if raw_df.empty or len(raw_df) < 200:
            log.warning("[%s] Insufficient 1h data returned (%d rows)", symbol, len(raw_df))
            return None

        raw_df = raw_df.reset_index()
        raw_df.columns = [str(c[0] if isinstance(c, tuple) else c).lower() for c in raw_df.columns]
        
        date_col = next((c for c in raw_df.columns if c in ["date", "datetime", "timestamp", "index"]), raw_df.columns[0])
        raw_df["timestamp"] = pd.to_datetime(raw_df[date_col]).astype("int64") // 10**9

        req_cols = ["timestamp", "open", "high", "low", "close", "volume"]
        clean_df = raw_df[req_cols].dropna().sort_values("timestamp").reset_index(drop=True)
        # Take the most recent bars_count
        if len(clean_df) > bars_count:
            clean_df = clean_df.iloc[-bars_count:].reset_index(drop=True)
        log.info("[%s] Fetched %d 1-hour bars", symbol, len(clean_df))
        return clean_df

    except Exception as e:
        log.error("[%s] Error downloading stock data: %s", symbol, e)
        return None


def fetch_crypto_1h_data(symbol: str, limit: int = 1000) -> Optional[pd.DataFrame]:
    """Downloads clean 1-hour OHLCV candle data via Binance CCXT with yfinance fallback."""
    try:
        exchange = ccxt.binance({"enableRateLimit": True, "timeout": 15000})
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe="1h", limit=limit)
        if not ohlcv or len(ohlcv) < 100:
            raise ValueError(f"Too few candles ({len(ohlcv)}) from Binance")

        df = pd.DataFrame(ohlcv, columns=["timestamp", "open", "high", "low", "close", "volume"])
        df["timestamp"] = df["timestamp"] // 1000
        for col in ["open", "high", "low", "close", "volume"]:
            df[col] = df[col].astype(float)
        log.info("[%s] Fetched %d 1-hour bars via Binance CCXT", symbol, len(df))
        return df

    except Exception as e:
        log.warning("[%s] Binance CCXT failed (%s), falling back to Yahoo Finance...", symbol, e)
        yf_sym = symbol.replace("/", "-")
        try:
            raw_df = yf.download(yf_sym, period="730d", interval="1h", progress=False)
            if raw_df.empty:
                return None
            raw_df = raw_df.reset_index()
            raw_df.columns = [str(c[0] if isinstance(c, tuple) else c).lower() for c in raw_df.columns]
            date_col = next((c for c in raw_df.columns if c in ["date", "datetime", "timestamp", "index"]), raw_df.columns[0])
            raw_df["timestamp"] = pd.to_datetime(raw_df[date_col]).astype("int64") // 10**9
            req_cols = ["timestamp", "open", "high", "low", "close", "volume"]
            clean_df = raw_df[req_cols].dropna().sort_values("timestamp").reset_index(drop=True)
            if len(clean_df) > limit:
                clean_df = clean_df.iloc[-limit:].reset_index(drop=True)
            log.info("[%s] Fetched %d 1-hour bars via Yahoo fallback", symbol, len(clean_df))
            return clean_df
        except Exception as ex:
            log.error("[%s] Yahoo fallback also failed: %s", symbol, ex)
            return None


def enrich_with_all_plugins(symbol: str, df: pd.DataFrame, asset_class: str) -> pd.DataFrame:
    """
    Enriches DataFrame with ALL 10 strategy plugins:
    - 6 Native TRDENG Strategies: BB Pattern, HA SAR, Dual Thrust, ORB, VPOC, NFI
    - 4 Quant Signal Plugins: Dual Thrust direction, Awesome Oscillator, HA Trend, RSI Divergence
    """
    df = df.copy()

    # 1. Base technical features
    df = compute_standard_features(df)

    # 2. Quant Signal Plugins
    quant_signals = QuantStrategyBridge.get_all_quant_signals(df)
    for sig_name, sig_series in quant_signals.items():
        df[f"plugin_{sig_name}"] = sig_series.values

    # 3. Native TRDENG Strategy Plugins
    bridge = NativeStrategiesBridge(asset_class=asset_class)
    df = bridge.enrich_dataframe(symbol, df)

    return df


def train_single_asset(
    symbol: str,
    df: pd.DataFrame,
    asset_class: str,
    initial_equity: float = 1000.0,
    leverage: float = 5.0,
    stop_loss_pct: float = 0.06,
    take_profit_pct: float = 0.10,
    timesteps: int = 5000,
    output_base_dir: str = "model_weights/multimarket_rl"
) -> Dict[str, Any]:
    """Trains walk-forward PPO with dynamic strategy plugins and exports frozen ONNX model."""
    os.makedirs(output_base_dir, exist_ok=True)
    sym_clean = symbol.replace("/", "_").lower()
    asset_dir = os.path.join(output_base_dir, sym_clean)
    os.makedirs(asset_dir, exist_ok=True)

    # Inject all plugins into dataframe
    df = enrich_with_all_plugins(symbol, df, asset_class=asset_class)

    cfg = TrainRLConfig(
        symbol=symbol,
        n_folds=2,
        seeds=[42, 43],
        embargo_bars=15,
        total_timesteps=timesteps,
        n_steps=128,
        batch_size=64,
        min_holding_bars=3,
        initial_equity=initial_equity,
        output_dir=os.path.join(asset_dir, "runs")
    )

    t0 = time.time()
    results = run_walk_forward_training(df, config=cfg)
    train_duration = time.time() - t0

    # Fit normalizer on full dataset (will dynamically capture all strat_ and plugin_ columns)
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
            "source": "ccxt_binance" if asset_class == "crypto" else "yahoo_finance_1h",
            "asset_class": asset_class,
            "learning_rate": cfg.learning_rate,
            "leverage": leverage,
            "initial_equity": initial_equity,
            "stop_loss_pct": stop_loss_pct,
            "take_profit_pct": take_profit_pct,
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
        "asset_class": asset_class,
        "leverage": leverage,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "verdict": results["verdict"],
        "mean_sharpe": results["global_mean_sharpe"],
        "mean_return_pct": round(mean_ret, 2),
        "mean_max_dd_pct": round(mean_dd, 2),
        "overall_dsr": results["deflated_sharpe_ratio"],
        "observation_dim": len(prod_env.all_feature_names),
        "training_time_sec": round(train_duration, 1),
        "onnx_model_path": onnx_file,
        "meta_path": meta_file
    }


def process_target(item: Tuple[str, str, float]) -> Optional[Dict[str, Any]]:
    """Worker task: item is (symbol, asset_class, leverage)."""
    sym, asset_class, lev = item
    try:
        if asset_class == "crypto":
            df = fetch_crypto_1h_data(sym, limit=1000)
        else:
            df = fetch_stock_1h_data(sym, bars_count=1500)

        if df is None:
            return None

        res = train_single_asset(
            symbol=sym,
            df=df,
            asset_class=asset_class,
            initial_equity=1000.0,
            leverage=lev,
            stop_loss_pct=0.06,
            take_profit_pct=0.10,
            timesteps=4000
        )
        return res
    except Exception as e:
        log.error("Error processing %s: %s", sym, e, exc_info=True)
        return None


def main():
    print("\n" + "=" * 80)
    print(" TRDENG MULTI-MARKET RL: 5 US STOCKS + 2 CRYPTO (1-HOUR BARS)")
    print(" Stocks (5x Lev): AAPL, MSFT, NVDA, AMZN, TSLA")
    print(" Crypto (10x Lev): BTC/USDT, ETH/USDT")
    print(" All 10 Plugins: BB Pattern, HA SAR, Dual Thrust, ORB, VPOC, NFI + AO, RSI")
    print(" Capital: $1,000 | Guardrails: 6% Stop-Loss, 10% Profit Target")
    print("=" * 80 + "\n")

    targets = [
        # (symbol, asset_class, leverage)
        ("BTC/USDT", "crypto", 10.0),
        ("ETH/USDT", "crypto", 10.0),
        ("AAPL", "us_equity", 5.0),
        ("NVDA", "us_equity", 5.0),
        ("TSLA", "us_equity", 5.0),
        ("MSFT", "us_equity", 5.0),
        ("AMZN", "us_equity", 5.0),
    ]

    leaderboard: List[Dict[str, Any]] = []
    t_start = time.time()
    total = len(targets)

    print(f"--> Launching training across {total} targets (2 parallel workers)...")
    with ThreadPoolExecutor(max_workers=2) as executor:
        future_map = {executor.submit(process_target, item): item[0] for item in targets}
        completed = 0
        for fut in as_completed(future_map):
            completed += 1
            sym = future_map[fut]
            res = fut.result()
            if res:
                leaderboard.append(res)
                print(
                    f"[{completed:02d}/{total}] {res['symbol']:<10} | Class: {res['asset_class']:<9} | "
                    f"Sharpe: {res['mean_sharpe']:>5.2f} | Net Ret: {res['mean_return_pct']:>6.1f}% | "
                    f"MaxDD: {res['mean_max_dd_pct']:>5.1f}% | ObsDim: {res['observation_dim']:>2d} | "
                    f"Lev: {res['leverage']:>2.0f}x"
                )

    total_time = time.time() - t_start

    # Save summary
    summary_path = "model_weights/multimarket_rl/training_summary.json"
    os.makedirs(os.path.dirname(summary_path), exist_ok=True)
    with open(summary_path, "w", encoding="utf-8") as f:
        json.dump(leaderboard, f, indent=2)

    print("\n" + "=" * 85)
    print(f" MULTI-MARKET RL TRAINING SUMMARY ({len(leaderboard)} Models in {total_time:.1f}s)")
    print("=" * 85)
    print(f"{'Symbol':<10} {'Class':<10} {'Lev':<5} {'Sharpe':<8} {'Return %':<10} {'Max DD %':<10} {'ObsDim':<8} {'Verdict':<8}")
    print("-" * 85)
    for r in sorted(leaderboard, key=lambda x: x["mean_sharpe"], reverse=True):
        print(f"{r['symbol']:<10} {r['asset_class']:<10} {r['leverage']:<5.0f} {r['mean_sharpe']:<8.2f} {r['mean_return_pct']:<10.1f} {r['mean_max_dd_pct']:<10.1f} {r['observation_dim']:<8} {r['verdict']:<8}")
    print("=" * 85)
    print(f"Exported models and summary to {summary_path}\n")


if __name__ == "__main__":
    main()
