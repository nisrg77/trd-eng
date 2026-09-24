"""
research/rl/native_strategies_bridge.py — Bridge for Native TRDENG Strategies into RL

Directly connects the production strategies in the strategies/ folder:
1. BollingerPatternStrategy (W-bottom / M-top harmonic recognition)
2. HeikinAshiSARStrategy (Smoothed Heikin-Ashi + Parabolic SAR trend)
3. DualThrustStrategy (Adaptive volatility breakout channels)
4. ORBBreakoutStrategy (Opening Range Breakout)
5. VPOCReversionStrategy (Value Area / VPOC mean-reversion)
6. NFIStrategy (NostalgiaForInfinity adaptive momentum)

Generates causal, zero-lookahead signal series (-1.0, 0.0, +1.0) and conviction scores
to inject as features into the RL state space.
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional
import numpy as np
import pandas as pd

from data_pipeline.feature_standardizer import compute_standard_features
from strategies.bollinger_pattern import BollingerPatternStrategy
from strategies.heikin_ashi_sar import HeikinAshiSARStrategy
from strategies.dual_thrust import DualThrustStrategy
from strategies.stocks.orb_breakout import ORBBreakoutStrategy
from strategies.stocks.vpoc_reversion import VPOCReversionStrategy
from strategies.crypto.nfi_strategy import NFIStrategy

log = logging.getLogger(__name__)


class NativeStrategiesBridge:
    """
    Evaluates native TRDENG strategies across historical data frames
    to produce features and expert sub-policy inputs for RL training.
    """

    def __init__(self, asset_class: str = "crypto") -> None:
        self.asset_class = asset_class
        
        # Instantiate native strategy plugins
        self.strat_bb = BollingerPatternStrategy(strategy_id="strat_bb_pattern_01", asset_class=asset_class)
        self.strat_ha = HeikinAshiSARStrategy(strategy_id="strat_ha_sar_01", asset_class=asset_class)
        self.strat_dt = DualThrustStrategy(strategy_id="strat_dual_thrust_01", asset_class=asset_class)
        self.strat_orb = ORBBreakoutStrategy(strategy_id="stock_orb_01", params={"check_session_hours": False})
        self.strat_vpoc = VPOCReversionStrategy(strategy_id="stock_vpoc_01")
        self.strat_nfi = NFIStrategy(strategy_id="crypto_nfi_01")

    def generate_strategy_signals(self, symbol: str, df: pd.DataFrame) -> Dict[str, np.ndarray]:
        """
        Computes rolling causal signals (-1.0, 0.0, +1.0) for each native strategy.
        """
        n = len(df)
        sig_bb = np.zeros(n, dtype=np.float32)
        sig_ha = np.zeros(n, dtype=np.float32)
        sig_dt = np.zeros(n, dtype=np.float32)
        sig_orb = np.zeros(n, dtype=np.float32)
        sig_vpoc = np.zeros(n, dtype=np.float32)
        sig_nfi = np.zeros(n, dtype=np.float32)

        # Standardize features once
        df_feat = compute_standard_features(df.copy())

        # Evaluate over sliding causal windows
        min_lookback = 30
        for i in range(min_lookback, n):
            sub_df = df_feat.iloc[:i + 1]

            # 1. Bollinger Pattern
            p_bb = self.strat_bb.generate_signal(symbol, sub_df)
            if p_bb:
                sig_bb[i] = float(p_bb.direction)

            # 2. Heikin-Ashi SAR
            p_ha = self.strat_ha.generate_signal(symbol, sub_df)
            if p_ha:
                sig_ha[i] = float(p_ha.direction)

            # 3. Dual Thrust
            p_dt = self.strat_dt.generate_signal(symbol, sub_df)
            if p_dt:
                sig_dt[i] = float(p_dt.direction)

            # 4. ORB Breakout (stocks)
            p_orb = self.strat_orb.generate_signal(symbol, sub_df)
            if p_orb:
                sig_orb[i] = float(p_orb.direction)

            # 5. VPOC Reversion (stocks)
            p_vpoc = self.strat_vpoc.generate_signal(symbol, sub_df)
            if p_vpoc:
                sig_vpoc[i] = float(p_vpoc.direction)

            # 6. NFI Momentum (crypto)
            p_nfi = self.strat_nfi.generate_signal(symbol, sub_df)
            if p_nfi:
                sig_nfi[i] = float(p_nfi.direction)

        return {
            "strat_bb_pattern": sig_bb,
            "strat_ha_sar": sig_ha,
            "strat_dual_thrust": sig_dt,
            "strat_orb_breakout": sig_orb,
            "strat_vpoc_reversion": sig_vpoc,
            "strat_nfi_momentum": sig_nfi
        }

    def enrich_dataframe(self, symbol: str, df: pd.DataFrame) -> pd.DataFrame:
        """Enriches the dataframe with all native strategy signals."""
        signals = self.generate_strategy_signals(symbol, df)
        df_out = df.copy()
        for name, arr in signals.items():
            df_out[name] = arr
        return df_out
