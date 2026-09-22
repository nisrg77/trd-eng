"""
tests/baseline_tester.py — 100-Trade Baseline Tester for US Futures Pipeline

Bypasses ML models to execute 100 random 50/50 Long/Short paper trades.
Overrides Kelly Criterion to use a strict 1% risk cap ($100 max risk per trade, assuming a $10,000 account baseline).
Calculates allocations for CME Micro SSF contracts (10 shares/contract) and aborts if 1-contract minimum risk > $100.
"""

import random
import logging
import time

logging.basicConfig(level=logging.INFO, format="%(asctime)s [BASELINE] %(message)s")
log = logging.getLogger(__name__)

# Constants for baseline tester
NUM_TRADES = 100
ACCOUNT_BALANCE = 10000.0  # Assumed starting balance
RISK_CAP_PCT = 0.01        # 1% risk cap
MAX_RISK_DOLLARS = ACCOUNT_BALANCE * RISK_CAP_PCT  # $100
SHARES_PER_MICRO_CONTRACT = 10

class BaselineTester:
    def __init__(self):
        self.trades = []
        self.skipped_due_to_risk = 0
        self.wins = 0
        self.losses = 0
        self.pnl = 0.0

    def generate_simulated_market_data(self):
        """Simulate current market price and ATR for a random CME Micro SSF."""
        tickers = ["AAPL", "MSFT", "GOOGL", "AMZN", "META", "TSLA", "NVDA", "BRK.B", "JPM", "JNJ"]
        ticker = random.choice(tickers)
        
        # Random price between $50 and $500
        price = round(random.uniform(50.0, 500.0), 2)
        # Random ATR between 1% and 5% of price
        atr = round(price * random.uniform(0.01, 0.05), 2)
        return ticker, price, atr

    def run(self):
        log.info(f"Starting Baseline Tester: {NUM_TRADES} Random Trades")
        log.info(f"Risk Params: Max Risk = ${MAX_RISK_DOLLARS:.2f} (1% of ${ACCOUNT_BALANCE})")
        log.info("Contract Specs: CME Micro SSF (10 shares/contract)")
        log.info("-" * 50)

        for i in range(1, NUM_TRADES + 1):
            # 1. 50/50 Random Long/Short Entry
            direction = "LONG" if random.random() > 0.5 else "SHORT"
            
            # 2. Market Data
            ticker, price, atr = self.generate_simulated_market_data()
            
            # 3. Risk Calculation
            # Trailing stop distance is 1 ATR
            stop_distance = atr
            risk_per_share = stop_distance
            risk_per_contract = risk_per_share * SHARES_PER_MICRO_CONTRACT
            
            log_str = f"Trade {i:03d} | Sym: {ticker:<5} | Dir: {direction:<5} | Price: ${price:>6.2f} | ATR: ${atr:>5.2f} | Risk/Contract: ${risk_per_contract:>6.2f}"
            
            # 4. Filter: Abort if 1 contract risk > $100
            if risk_per_contract > MAX_RISK_DOLLARS:
                self.skipped_due_to_risk += 1
                log.info(f"{log_str} -> SKIPPED (Risk > Max allowed)")
                continue
                
            # 5. Position Sizing
            num_contracts = int(MAX_RISK_DOLLARS // risk_per_contract)
            total_risk = num_contracts * risk_per_contract
            
            # 6. Simulate Outcome (50/50 win/loss)
            # Win = 2x Risk (Risk/Reward 1:2)
            # Loss = 1x Risk
            won = random.random() > 0.5
            if won:
                trade_pnl = total_risk * 2.0
                self.wins += 1
            else:
                trade_pnl = -total_risk
                self.losses += 1
                
            self.pnl += trade_pnl
            self.trades.append({
                "trade_id": i,
                "ticker": ticker,
                "direction": direction,
                "contracts": num_contracts,
                "pnl": trade_pnl
            })
            log.info(f"{log_str} -> EXECUTED (PnL: ${trade_pnl:>7.2f})")
            
        # Summary
        log.info("-" * 50)
        log.info("BASELINE TEST COMPLETE")
        log.info(f"Total Attempts: {NUM_TRADES}")
        log.info(f"Trades Executed: {len(self.trades)}")
        log.info(f"Skipped (Risk > $100): {self.skipped_due_to_risk}")
        log.info(f"Win Rate: {self.wins / len(self.trades) * 100:.2f}% (Wins: {self.wins}, Losses: {self.losses})")
        log.info(f"Total PnL: ${self.pnl:.2f}")
        log.info("-" * 50)

if __name__ == "__main__":
    tester = BaselineTester()
    tester.run()
