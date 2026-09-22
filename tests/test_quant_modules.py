import sys
import os
import pytest
import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from brain.cpcv_validator import CombinatorialPurgedCV
from brain.hmm_regime import GaussianHMMRegimeDetector
from execution.risk import RiskGuard

def test_cpcv_splits():
    X = np.random.randn(100, 4)
    cv = CombinatorialPurgedCV(n_splits=5, n_test_folds=2, pct_embargo=0.01)
    splits = list(cv.split(X))
    assert len(splits) == 10
    
    for train_idx, test_idx in splits:
        assert len(train_idx) > 0
        assert len(test_idx) > 0
        assert len(set(train_idx).intersection(set(test_idx))) == 0

def test_asset_class_hmm_regime_classification():
    hmm = GaussianHMMRegimeDetector()
    
    # Test US Equities/Futures (1.5% vol threshold)
    res_us = hmm.predict_regime(garch_vol=0.020, rsi_14=65.0, obi=0.1, is_crypto=False)
    assert res_us["asset_class"] == "US_STOCK_FUTURES"
    
    # Test Crypto Futures (4.0% vol threshold)
    res_crypto = hmm.predict_regime(garch_vol=0.020, rsi_14=65.0, obi=0.1, is_crypto=True)
    assert res_crypto["asset_class"] == "CRYPTO_FUTURES"

def test_kelly_position_sizing():
    rg = RiskGuard()
    kelly_size = rg.calculate_kelly_size(win_probability=0.65, win_loss_ratio=1.5)
    assert 0.0 < kelly_size <= 0.20

def test_separated_circuit_breakers():
    rg = RiskGuard()
    rg.daily_start_equity = 1000.0
    
    # Test US Stock Futures (3% daily drawdown trigger -> 4% DD triggers rejection)
    order_us = {"instrument": "AAPL", "action": "BUY", "portfolio_allocation_pct": 0.1, "confidence": 0.6}
    checked_us = rg.check_order(order_us, current_equity=955.0) # 4.5% DD
    assert checked_us["risk_state"] == "REJECTED"
    assert checked_us["failed_check"] == "circuit_breaker_active"
    
    # Test Crypto Futures (6% daily drawdown threshold -> 4.5% DD is still APPROVED)
    order_crypto = {"instrument": "BTC-USD", "action": "BUY", "portfolio_allocation_pct": 0.1, "confidence": 0.6}
    checked_crypto = rg.check_order(order_crypto, current_equity=955.0) # 4.5% DD
    assert checked_crypto["risk_state"] == "APPROVED"
