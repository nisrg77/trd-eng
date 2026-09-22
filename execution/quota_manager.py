"""
execution/quota_manager.py — Trade Execution Quota Manager

Caps and logs the 100-trade baseline.
- 20 trades for Crypto Perpetuals
- 80 trades for US Stock Futures
Calculates Expectancy metric upon completion.
"""

import os
import json
import logging
import threading

log = logging.getLogger(__name__)

_QUOTA_FILE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "quota_state.json")
_lock = threading.Lock()

class QuotaManager:
    def __init__(self):
        self.target_crypto = 20
        self.target_futures = 80
        self._init_state()

    def _init_state(self):
        if not os.path.exists(_QUOTA_FILE):
            default_state = {
                "crypto": {"completed": 0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0},
                "futures": {"completed": 0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0}
            }
            self._write_state(default_state)

    def _read_state(self) -> dict:
        with _lock:
            try:
                with open(_QUOTA_FILE, "r") as f:
                    return json.load(f)
            except Exception:
                return {
                    "crypto": {"completed": 0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0},
                    "futures": {"completed": 0, "wins": 0, "losses": 0, "win_pnl": 0.0, "loss_pnl": 0.0}
                }

    def _write_state(self, state: dict):
        with _lock:
            with open(_QUOTA_FILE, "w") as f:
                json.dump(state, f, indent=2)

    def can_trade(self, asset_class: str) -> bool:
        """Returns True if the pipeline is allowed to trade."""
        state = self._read_state()
        if asset_class.lower() == "crypto":
            return state["crypto"]["completed"] < self.target_crypto
        elif asset_class.lower() == "futures":
            return state["futures"]["completed"] < self.target_futures
        return False

    def is_baseline_complete(self) -> bool:
        """Returns True if all 100 trades are completed."""
        state = self._read_state()
        return (state["crypto"]["completed"] >= self.target_crypto and 
                state["futures"]["completed"] >= self.target_futures)

    def log_closed_trade(self, asset_class: str, pnl: float):
        """Logs a closed trade and evaluates if quota is met."""
        state = self._read_state()
        ac = asset_class.lower()
        
        if ac not in ["crypto", "futures"]:
            log.warning(f"[QuotaManager] Unknown asset class: {asset_class}")
            return
            
        state[ac]["completed"] += 1
        if pnl > 0:
            state[ac]["wins"] += 1
            state[ac]["win_pnl"] += pnl
        else:
            state[ac]["losses"] += 1
            state[ac]["loss_pnl"] += abs(pnl)
            
        self._write_state(state)
        
        completed = state[ac]["completed"]
        target = self.target_crypto if ac == "crypto" else self.target_futures
        
        log.info(f"[QuotaManager] {asset_class.upper()} Trade Closed. Progress: {completed}/{target}")
        
        if completed == target:
            log.warning(f"[QuotaManager] {asset_class.upper()} PIPELINE HAS REACHED QUOTA ({target} trades). Auto-throttling active.")
            
        if self.is_baseline_complete():
            self._calculate_expectancy(state)

    def _calculate_expectancy(self, state: dict):
        total_wins = state["crypto"]["wins"] + state["futures"]["wins"]
        total_losses = state["crypto"]["losses"] + state["futures"]["losses"]
        total_trades = total_wins + total_losses
        
        if total_trades == 0:
            return
            
        p_win = total_wins / total_trades
        p_loss = total_losses / total_trades
        
        total_win_pnl = state["crypto"]["win_pnl"] + state["futures"]["win_pnl"]
        total_loss_pnl = state["crypto"]["loss_pnl"] + state["futures"]["loss_pnl"]
        
        avg_win = total_win_pnl / total_wins if total_wins > 0 else 0
        avg_loss = total_loss_pnl / total_losses if total_losses > 0 else 0
        
        expectancy = (p_win * avg_win) - (p_loss * avg_loss)
        
        log.info("=" * 60)
        log.info("🎯 100-TRADE BASELINE AUDIT COMPLETE 🎯")
        log.info(f"Total Trades: {total_trades}")
        log.info(f"Win Rate: {p_win*100:.2f}% (Wins: {total_wins}, Losses: {total_losses})")
        log.info(f"Average Win: ${avg_win:.2f}")
        log.info(f"Average Loss: ${avg_loss:.2f}")
        log.info(f"NET EXPECTANCY: ${expectancy:.2f} per trade")
        log.info("=" * 60)
        
        self.export_csv_results(state, expectancy, p_win, total_trades)

    def export_csv_results(self, state: dict, expectancy: float, win_rate: float, total_trades: int):
        import pandas as pd
        
        exec_file = os.path.join(os.path.dirname(os.path.dirname(__file__)), "execution_store.json")
        try:
            with open(exec_file, "r") as f:
                executions = json.load(f)
        except Exception:
            executions = []
            
        if not executions:
            log.warning("[QuotaManager] No executions found to export.")
            return
            
        df = pd.DataFrame(executions)
        
        csv_path = os.path.join(os.path.dirname(os.path.dirname(__file__)), "final_baseline_results.csv")
        df.to_csv(csv_path, index=False)
        log.info(f"[QuotaManager] Baseline results exported to: {csv_path}")
        
        # Append summary metrics to the bottom of the CSV
        with open(csv_path, "a") as f:
            f.write("\n\n--- SUMMARY METRICS ---\n")
            f.write(f"Total Trades,{total_trades}\n")
            f.write(f"Crypto Completed,{state['crypto']['completed']}\n")
            f.write(f"US Futures Completed,{state['futures']['completed']}\n")
            f.write(f"Win Rate,{win_rate*100:.2f}%\n")
            f.write(f"Net Expectancy,${expectancy:.2f}\n")
            
        log.warning("[QuotaManager] Baseline complete. Halting engine execution gracefully.")
        # In a real environment, you might issue a kill signal or set a global HALT flag in Redis.
        # Here we just rely on can_trade returning False continuously.

# Singleton
quota_manager = QuotaManager()
