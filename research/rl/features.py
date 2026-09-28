"""
research/rl/features.py — Microstructure, Order Book, Institutional & Sentiment Feature Pipeline

Extracts 8 advanced microstructure, order book, institutional, and sentiment dimensions:
1. ofi                      : Order Flow Imbalance across top quotes.
2. norm_spread_atr          : Normalized Bid-Ask Spread Dynamics relative to 100-bar rolling mean.
3. queue_depletion_velocity : Top-3 Queue Depletion / Cancellation Velocity.
4. vpin                     : Volume-Synchronized Probability of Toxicity (Easley et al. 2012).
5. cvd_norm_vol20           : Cumulative Volume Delta (CVD) normalized by 20-bar volume.
6. block_trade_density      : Rolling frequency of institutional block trades (>99th percentile).
7. event_polarity_shift     : Real-time news/NLP sentiment score deviation from 24h baseline.
8. vol_anticipation_index   : Volatility Anticipation Index (sentiment deviation vs. IV skew).

Operates both in real-time streaming mode (Level 2 depth & trade ticks) and
vectorized causal batch mode for historical backtesting and offline training.
"""

from __future__ import annotations
import math
import collections
import logging
from typing import Dict, Any, List, Optional, Tuple

import numpy as np
import pandas as pd

from data_pipeline.feature_standardizer import compute_standard_features

log = logging.getLogger(__name__)

MICROSTRUCTURE_FEATURE_NAMES: List[str] = [
    "ofi",
    "norm_spread_atr",
    "queue_depletion_velocity",
    "vpin",
    "cvd_norm_vol20",
    "block_trade_density",
    "event_polarity_shift",
    "vol_anticipation_index"
]


class MicrostructureFeatureExtractor:
    """
    Streaming and batch feature extractor for the 8 microstructure dimensions.
    """

    def __init__(
        self,
        vpin_buckets: int = 10,
        spread_rolling_window: int = 100,
        block_percentile: float = 99.0,
        sentiment_baseline_window: int = 24
    ) -> None:
        self.vpin_buckets = vpin_buckets
        self.spread_rolling_window = spread_rolling_window
        self.block_percentile = block_percentile
        self.sentiment_baseline_window = sentiment_baseline_window

        # Live streaming states
        self._prev_bids: List[Tuple[float, float]] = []  # [(price, size), ...]
        self._prev_asks: List[Tuple[float, float]] = []
        self._prev_top3_depth: float = 0.0
        self._spread_history: collections.deque = collections.deque(maxlen=spread_rolling_window)
        self._trade_sizes: collections.deque = collections.deque(maxlen=1000)
        self._recent_trades: collections.deque = collections.deque(maxlen=200)
        self._sentiment_history: collections.deque = collections.deque(maxlen=sentiment_baseline_window)
        self._current_sentiment: float = 0.0
        self._current_iv_skew: float = 0.0
        self._cumulative_vol_delta: float = 0.0
        self._rolling_volumes: collections.deque = collections.deque(maxlen=20)

    def on_order_book_update(
        self,
        bids: List[Tuple[float, float]],
        asks: List[Tuple[float, float]],
        timestamp: float = 0.0
    ) -> Dict[str, float]:
        """
        Processes a Level 2 depth snapshot update and updates OFI, Spread, and Queue Depletion.
        bids: sorted high to low [(px, sz), ...]
        asks: sorted low to high [(px, sz), ...]
        """
        if not bids or not asks:
            return {}

        best_bid_px, best_bid_sz = bids[0]
        best_ask_px, best_ask_sz = asks[0]
        spread = max(1e-6, best_ask_px - best_bid_px)
        self._spread_history.append(spread)

        # 1. Order Flow Imbalance (OFI) across top quotes (Cont, Kukanov, Stoikov 2014)
        ofi_val = 0.0
        if self._prev_bids and self._prev_asks:
            prev_bid_px, prev_bid_sz = self._prev_bids[0]
            prev_ask_px, prev_ask_sz = self._prev_asks[0]

            # Bid side contribution
            if best_bid_px > prev_bid_px:
                delta_bid = best_bid_sz
            elif best_bid_px < prev_bid_px:
                delta_bid = 0.0
            else:
                delta_bid = best_bid_sz - prev_bid_sz

            # Ask side contribution
            if best_ask_px > prev_ask_px:
                delta_ask = 0.0
            elif best_ask_px < prev_ask_px:
                delta_ask = best_ask_sz
            else:
                delta_ask = best_ask_sz - prev_ask_sz

            avg_depth = max(1e-4, (best_bid_sz + best_ask_sz + prev_bid_sz + prev_ask_sz) / 4.0)
            ofi_val = (delta_bid - delta_ask) / avg_depth

        # 2. Top-3 Queue Depletion / Cancellation Velocity
        top3_depth = sum(sz for _, sz in bids[:3]) + sum(sz for _, sz in asks[:3])
        depletion_velocity = 0.0
        if self._prev_top3_depth > 0:
            depth_delta = top3_depth - self._prev_top3_depth
            if depth_delta < 0:
                depletion_velocity = abs(depth_delta) / max(1e-4, self._prev_top3_depth)
        self._prev_top3_depth = top3_depth

        self._prev_bids = list(bids)
        self._prev_asks = list(asks)

        return {
            "ofi_step": ofi_val,
            "spread": spread,
            "depletion_velocity": depletion_velocity
        }

    def on_trade_tick(
        self,
        price: float,
        size: float,
        side: str,  # "buy" or "sell"
        timestamp: float = 0.0
    ) -> None:
        """Processes an incoming executed trade tick."""
        self._trade_sizes.append(size)
        direction = 1.0 if side.lower() == "buy" else -1.0
        self._cumulative_vol_delta += direction * size
        self._recent_trades.append({
            "price": price,
            "size": size,
            "direction": direction,
            "timestamp": timestamp
        })

    def on_sentiment_event(
        self,
        sentiment_score: float,  # [-1.0, 1.0]
        iv_skew: float = 0.0,
        timestamp: float = 0.0
    ) -> None:
        """Processes real-time NLP sentiment and options skew updates."""
        self._current_sentiment = float(np.clip(sentiment_score, -1.0, 1.0))
        self._current_iv_skew = float(iv_skew)
        self._sentiment_history.append(self._current_sentiment)

    @staticmethod
    def compute_features_df(df: pd.DataFrame) -> pd.DataFrame:
        """
        Causally calculates all 8 microstructure, institutional, and sentiment
        features over a DataFrame, ensuring strict zero lookahead.
        If explicit L2/tick fields are missing, computes high-fidelity causal proxies
        from bar range, volume structure, and volatility dynamics.
        """
        out = df.copy()
        n = len(out)
        if n < 5:
            for feat in MICROSTRUCTURE_FEATURE_NAMES:
                if feat not in out.columns:
                    out[feat] = 0.0
            return out

        # Compute standard ATR if not present
        if "atr_14" not in out.columns:
            features_df = compute_standard_features(out)
            out["atr_14"] = features_df["atr_14"]

        close = out["close"].astype(np.float64)
        open_px = out["open"].astype(np.float64)
        high = out["high"].astype(np.float64)
        low = out["low"].astype(np.float64)
        volume = out["volume"].astype(np.float64).clip(lower=1e-6)
        atr = out["atr_14"].clip(lower=1e-6)

        # ---------------------------------------------------------------------
        # 1. Order Flow Imbalance (OFI)
        # ---------------------------------------------------------------------
        if "ofi" not in out.columns:
            # Causal proxy: bar price pressure weighted by volume relative to rolling volume
            # OFI_proxy = (2*close - high - low) / (high - low + eps) * (vol / vol_sma20)
            hl_range = (high - low).clip(lower=1e-6)
            bar_pressure = (2.0 * close - high - low) / hl_range
            vol_sma20 = volume.rolling(20, min_periods=1).mean()
            vol_ratio = (volume / vol_sma20).clip(upper=5.0)
            out["ofi"] = (bar_pressure * vol_ratio).clip(-5.0, 5.0).fillna(0.0)

        # ---------------------------------------------------------------------
        # 2. Normalized Bid-Ask Spread Dynamics (ATR-normalized to 100-bar rolling mean)
        # ---------------------------------------------------------------------
        if "norm_spread_atr" not in out.columns:
            if "spread" in out.columns:
                raw_spread = out["spread"].astype(np.float64)
            else:
                # Corwin-Schultz / Roll effective spread proxy from High/Low & Open/Close
                # Spread ~ 0.5 * ATR * (1 - abs(Close - Open) / (High - Low + eps))
                spread_proxy = 0.1 * atr * (1.0 + np.abs(close - open_px) / (high - low + 1e-6))
                raw_spread = spread_proxy

            spread_roll_mean = raw_spread.rolling(100, min_periods=5).mean().fillna(raw_spread)
            out["norm_spread_atr"] = ((raw_spread - spread_roll_mean) / atr).clip(-5.0, 5.0).fillna(0.0)

        # ---------------------------------------------------------------------
        # 3. Top-3 Queue Depletion / Cancellation Velocity
        # ---------------------------------------------------------------------
        if "queue_depletion_velocity" not in out.columns:
            # Velocity: Rate at which liquidity depth contracts without proportional price progress
            # Wick contraction velocity = (upper_wick + lower_wick) / (body + eps) * delta_vol
            body = (close - open_px).abs().clip(lower=1e-6)
            wicks = (high - low) - body
            wick_ratio = (wicks / body).clip(upper=10.0)
            vol_accel = (volume / volume.shift(1).clip(lower=1e-6) - 1.0).fillna(0.0)
            out["queue_depletion_velocity"] = np.tanh(wick_ratio * vol_accel).clip(-5.0, 5.0).fillna(0.0)

        # ---------------------------------------------------------------------
        # 4. Volume-Synchronized Probability of Toxicity (VPIN)
        # ---------------------------------------------------------------------
        if "vpin" not in out.columns:
            # Easley et al. 2012 VPIN calculation over volume buckets
            # Buy volume fraction estimated via normal CDF of standardized return
            rets = np.log(close / close.shift(1).clip(lower=1e-6)).fillna(0.0)
            roll_ret_std = rets.rolling(20, min_periods=3).std().clip(lower=1e-6)
            z_score = rets / roll_ret_std
            # Approximate standard normal CDF: Phi(z) ~ 0.5 * (1 + tanh(z * sqrt(2/pi)))
            buy_vol_frac = 0.5 * (1.0 + np.tanh(z_score * math.sqrt(2.0 / math.pi)))
            buy_vol = volume * buy_vol_frac
            sell_vol = volume * (1.0 - buy_vol_frac)
            order_imbalance = (buy_vol - sell_vol).abs()
            rolling_imbalance = order_imbalance.rolling(10, min_periods=1).sum()
            rolling_total_vol = volume.rolling(10, min_periods=1).sum().clip(lower=1e-6)
            out["vpin"] = (rolling_imbalance / rolling_total_vol).clip(0.0, 1.0).fillna(0.3)

        # ---------------------------------------------------------------------
        # 5. Cumulative Volume Delta (CVD) Normalized by 20-bar Volume
        # ---------------------------------------------------------------------
        if "cvd_norm_vol20" not in out.columns:
            # Directional volume delta = (2 * (Close - Low)/(High - Low) - 1) * Volume
            delta_vol = (2.0 * (close - low) / (high - low + 1e-6) - 1.0) * volume
            cvd = delta_vol.rolling(20, min_periods=1).sum()
            vol_20 = volume.rolling(20, min_periods=1).sum().clip(lower=1e-6)
            out["cvd_norm_vol20"] = (cvd / vol_20).clip(-3.0, 3.0).fillna(0.0)

        # ---------------------------------------------------------------------
        # 6. Block Trade Density (>99th percentile trade size frequency)
        # ---------------------------------------------------------------------
        if "block_trade_density" not in out.columns:
            # Detect bars with outsized volume spikes (>99th percentile of rolling volume)
            vol_p99 = volume.rolling(100, min_periods=10).quantile(0.99).fillna(volume * 2.0)
            block_indicator = (volume >= vol_p99).astype(np.float64)
            out["block_trade_density"] = block_indicator.rolling(20, min_periods=1).mean().clip(0.0, 1.0).fillna(0.0)

        # ---------------------------------------------------------------------
        # 7. Event Polarity Shift (Real-time news NLP score deviation from 24h baseline)
        # ---------------------------------------------------------------------
        if "event_polarity_shift" not in out.columns:
            if "sentiment_score" in out.columns:
                sent = out["sentiment_score"].astype(np.float64)
            else:
                # In absence of direct news stream, use price-momentum sentiment proxy
                # Normalized 5-bar vs 24-bar return deviation
                r5 = np.log(close / close.shift(5).clip(lower=1e-6)).fillna(0.0)
                sent = np.tanh(r5 * 10.0)

            sent_24_mean = sent.rolling(24, min_periods=3).mean().fillna(0.0)
            sent_24_std = sent.rolling(24, min_periods=3).std().clip(lower=0.05).fillna(0.1)
            out["event_polarity_shift"] = ((sent - sent_24_mean) / sent_24_std).clip(-5.0, 5.0).fillna(0.0)

        # ---------------------------------------------------------------------
        # 8. Volatility Anticipation Index (Sentiment deviation vs. IV skew)
        # ---------------------------------------------------------------------
        if "vol_anticipation_index" not in out.columns:
            # IV skew or realized upside vs downside semi-variance proxy
            rets = np.log(close / close.shift(1).clip(lower=1e-6)).fillna(0.0)
            pos_rets = rets.clip(lower=0.0)
            neg_rets = rets.clip(upper=0.0).abs()
            pos_vol = pos_rets.rolling(20, min_periods=3).std().fillna(0.01)
            neg_vol = neg_rets.rolling(20, min_periods=3).std().fillna(0.01)
            skew_proxy = (neg_vol - pos_vol) / (neg_vol + pos_vol + 1e-6)

            # Volatility anticipation = Sentiment Polarity Shift * Skew
            pol_shift = out["event_polarity_shift"]
            realized_vol = rets.rolling(20, min_periods=3).std().clip(lower=1e-4)
            out["vol_anticipation_index"] = (pol_shift * (skew_proxy / realized_vol)).clip(-5.0, 5.0).fillna(0.0)

        return out
