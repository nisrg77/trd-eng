"""
middleware/webhooks.py — Telegram & Discord Webhook Module

Pushes immediate risk alerts (like Circuit Breaker triggers) and End of Day summaries.
Reads webhook URLs from .env via config, but defaults to NOOP if not set.
"""

import os
import requests
import logging
from typing import Optional

import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger(__name__)

# Webhook URLs from env (could be added to config.py later)
DISCORD_WEBHOOK_URL = os.environ.get("DISCORD_WEBHOOK_URL")
TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID")

class WebhookAlerts:
    @staticmethod
    def send_discord_alert(message: str) -> bool:
        if not DISCORD_WEBHOOK_URL:
            return False
            
        payload = {"content": message}
        try:
            resp = requests.post(DISCORD_WEBHOOK_URL, json=payload, timeout=5)
            resp.raise_for_status()
            return True
        except Exception as e:
            log.error(f"[Webhook] Discord alert failed: {e}")
            return False

    @staticmethod
    def send_telegram_alert(message: str) -> bool:
        if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
            return False
            
        url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
        payload = {
            "chat_id": TELEGRAM_CHAT_ID,
            "text": message,
            "parse_mode": "Markdown"
        }
        try:
            resp = requests.post(url, json=payload, timeout=5)
            resp.raise_for_status()
            return True
        except Exception as e:
            log.error(f"[Webhook] Telegram alert failed: {e}")
            return False

    @classmethod
    def alert_circuit_breaker(cls, asset_class: str, drawdown_pct: float, threshold: float):
        """Send immediate alert when Circuit Breaker is triggered."""
        msg = (
            f"🚨 **CIRCUIT BREAKER TRIGGERED** 🚨\n\n"
            f"**Asset Class:** {asset_class}\n"
            f"**Current Drawdown:** {drawdown_pct*100:.2f}%\n"
            f"**Threshold:** {threshold*100:.2f}%\n\n"
            f"Trading for {asset_class} has been halted."
        )
        log.warning(f"[Webhook] Sending Circuit Breaker Alert: {asset_class}")
        cls.send_discord_alert(msg)
        cls.send_telegram_alert(msg)

    @classmethod
    def alert_trade_fill(cls, instrument: str, action: str, qty: float, price: float, pnl: Optional[float] = None):
        """Send alert on trade fill or close."""
        pnl_str = f"\n**Realized PnL:** ${pnl:.2f}" if pnl is not None else ""
        msg = (
            f"✅ **TRADE FILL** - {instrument}\n"
            f"**Action:** {action}\n"
            f"**Quantity:** {qty}\n"
            f"**Price:** ${price:.2f}"
            f"{pnl_str}"
        )
        cls.send_discord_alert(msg)
        cls.send_telegram_alert(msg)

    @classmethod
    def send_eod_summary(cls, realized_pnl: float, num_trades: int, active_positions: int):
        """Send End of Day summary report."""
        msg = (
            f"📊 **END OF DAY SUMMARY** 📊\n\n"
            f"**Realized PnL Today:** ${realized_pnl:.2f}\n"
            f"**Trades Executed:** {num_trades}\n"
            f"**Active Positions:** {active_positions}"
        )
        cls.send_discord_alert(msg)
        cls.send_telegram_alert(msg)

