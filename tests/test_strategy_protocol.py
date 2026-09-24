"""
tests/test_strategy_protocol.py — Tests for SignalPacket, BaseStrategy, and StrategyRegistry
"""

import pytest
import pandas as pd
import numpy as np
from core.signal_packet import SignalPacket
from strategies.base_strategy import BaseStrategy
from strategies.strategy_registry import StrategyRegistry


class DummyBullStrategy(BaseStrategy):
    def generate_signal(self, symbol: str, df: pd.DataFrame):
        return SignalPacket(
            strategy_id=self.strategy_id,
            asset_class=self.asset_class,
            symbol=symbol,
            direction=0.8,
            conviction=0.9,
            metadata={"trigger": "dummy_bull"}
        )


class FailingStrategy(BaseStrategy):
    def generate_signal(self, symbol: str, df: pd.DataFrame):
        raise ValueError("Simulated strategy breakdown!")


def test_signal_packet_clipping_and_serialization():
    # Test clipping
    sig = SignalPacket(
        strategy_id="strat_test",
        asset_class="crypto",
        symbol="BTC-USD",
        direction=2.5,  # should clip to 1.0
        conviction=-0.4  # should clip to 0.0
    )
    assert sig.direction == 1.0
    assert sig.conviction == 0.0
    assert not sig.is_actionable()

    # Test actionable
    sig_actionable = SignalPacket(
        strategy_id="strat_test",
        asset_class="crypto",
        symbol="BTC-USD",
        direction=0.6,
        conviction=0.75
    )
    assert sig_actionable.is_actionable()

    # Test serialization round-trip
    d = sig_actionable.to_dict()
    assert d["symbol"] == "BTC-USD"
    assert d["direction"] == 0.6
    sig_reconstructed = SignalPacket.from_dict(d)
    assert sig_reconstructed == sig_actionable


def test_strategy_parameter_update_and_toggle():
    strat = DummyBullStrategy("bull_01", "Bull Momentum", "crypto", params={"rsi_len": 14})
    assert strat.is_active is True
    assert strat.params["rsi_len"] == 14

    strat.update_parameters({"rsi_len": 21, "atr_mult": 2.5})
    assert strat.params["rsi_len"] == 21
    assert strat.params["atr_mult"] == 2.5

    strat.set_active(False)
    assert strat.is_active is False


def test_strategy_registry_and_isolation():
    reg = StrategyRegistry()
    s1 = DummyBullStrategy("bull_01", "Bull Momentum", "crypto")
    s2 = FailingStrategy("fail_01", "Failing Strategy", "crypto")

    reg.register(s1)
    reg.register(s2)

    assert len(reg.list_strategies()) == 2
    assert len(reg.list_strategies(asset_class="crypto")) == 2
    assert len(reg.list_strategies(asset_class="stock")) == 0

    df_dummy = pd.DataFrame({"close": [100.0, 101.0, 102.0]})

    # Evaluation must NOT crash despite FailingStrategy raising ValueError!
    signals = reg.evaluate_all("BTC-USD", df_dummy, asset_class="crypto")

    # s1 succeeded and returned 1 signal; s2 failed safely
    assert len(signals) == 1
    assert signals[0].strategy_id == "bull_01"
    assert signals[0].symbol == "BTC-USD"
    assert signals[0].direction == 0.8
