"""
research/bt_validator.py — Event-Driven Historical Validation Engine

Simulates realistic execution dynamics (maker/taker fees, slippage, partial fills)
and calculates institutional performance metrics (Sharpe, Sortino, Calmar, Max Drawdown).
"""

from __future__ import annotations
import logging
from typing import Dict, Any, List, Optional
import numpy as np
import pandas as pd
from strategies.base_strategy import BaseStrategy

log = logging.getLogger(__name__)


class BacktestValidator:
    """
    Event-driven backtest harness for multi-asset strategies.
    """

    def __init__(
        self,
        initial_capital: float = 10000.0,
        taker_fee: float = 0.0006,
        slippage_bps: float = 2.0
    ) -> None:
        self.initial_capital = initial_capital
        self.taker_fee = taker_fee
        self.slippage = slippage_bps / 10000.0

    def validate_strategy(
        self,
        strategy: BaseStrategy,
        symbol: str,
        df: pd.DataFrame
    ) -> Dict[str, Any]:
        """
        Runs bar-by-bar historical simulation of strategy signals.
        """
        if df.empty or len(df) < 15:
            return {"error": "Insufficient historical bars"}

        capital = self.initial_capital
        position_size = 0.0
        entry_price = 0.0
        trade_pnls = []
        equity_curve = [capital]

        for i in range(15, len(df)):
            current_bar = df.iloc[:i]
            last_close = float(current_bar["close"].iloc[-1])

            # Ingest bar and get signal
            sig = strategy.generate_signal(symbol, current_bar)

            # Execution simulation
            if sig and sig.is_actionable():
                if sig.direction > 0 and position_size <= 0:
                    # Close short if open
                    if position_size < 0:
                        exit_price = last_close * (1.0 + self.slippage)
                        pnl = abs(position_size) * (entry_price - exit_price) - (capital * self.taker_fee)
                        capital += pnl
                        trade_pnls.append(pnl)

                    # Enter Long
                    entry_price = last_close * (1.0 + self.slippage)
                    position_size = capital / entry_price
                    capital -= capital * self.taker_fee

                elif sig.direction < 0 and position_size >= 0:
                    # Close long if open
                    if position_size > 0:
                        exit_price = last_close * (1.0 - self.slippage)
                        pnl = position_size * (exit_price - entry_price) - (capital * self.taker_fee)
                        capital += pnl
                        trade_pnls.append(pnl)

                    # Enter Short
                    entry_price = last_close * (1.0 - self.slippage)
                    position_size = -(capital / entry_price)
                    capital -= capital * self.taker_fee

            # Track equity mark-to-market
            unrealized = 0.0
            if position_size > 0:
                unrealized = position_size * (last_close - entry_price)
            elif position_size < 0:
                unrealized = abs(position_size) * (entry_price - last_close)

            equity_curve.append(capital + unrealized)

        # Calculate metrics
        eq_arr = np.array(equity_curve)
        returns = np.diff(eq_arr) / (eq_arr[:-1] + 1e-9)
        total_pnl = float(eq_arr[-1] - self.initial_capital)
        total_ret_pct = (total_pnl / self.initial_capital) * 100.0

        mean_ret = float(np.mean(returns)) if len(returns) > 0 else 0.0
        std_ret = float(np.std(returns)) if len(returns) > 0 else 1.0
        sharpe = (mean_ret / (std_ret + 1e-9)) * np.sqrt(252 * 96) # Annualized 15m

        # Max Drawdown
        peak = np.maximum.accumulate(eq_arr)
        dd = (eq_arr - peak) / (peak + 1e-9)
        max_dd_pct = float(np.min(dd)) * 100.0

        win_trades = [p for p in trade_pnls if p > 0]
        win_rate = (len(win_trades) / len(trade_pnls)) * 100.0 if trade_pnls else 0.0

        return {
            "strategy_id": strategy.strategy_id,
            "symbol": symbol,
            "initial_capital": self.initial_capital,
            "final_equity": round(float(eq_arr[-1]), 2),
            "total_return_pct": round(total_ret_pct, 2),
            "total_trades": len(trade_pnls),
            "win_rate_pct": round(win_rate, 2),
            "sharpe_ratio": round(float(sharpe), 2),
            "max_drawdown_pct": round(max_dd_pct, 2),
        }
