"""
services/run_data_pipeline.py — [DP] Data Pipeline Service

Runnable microservice that:
  1. Fetches OHLCV data via yfinance for all INSTRUMENTS
  2. Computes frac-diff, GARCH vol, RSI, OBI features
  3. Publishes each instrument's feature payload to  tedeng:features

Usage:
    python services/run_data_pipeline.py
"""

import sys
import os
import json
import logging

# Project root on path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import config
from data_pipeline.pipeline import DataPipeline
from middleware.broker import Broker

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [DP-SERVICE] %(levelname)s  %(message)s",
    datefmt="%H:%M:%S",
)
log = logging.getLogger(__name__)


def main() -> None:
    log.info("Starting TEDENG Data Pipeline Service")
    log.info("Instruments : %s", config.INSTRUMENTS)
    log.info("Poll interval: %ds", config.POLL_INTERVAL_SECONDS)
    log.info("Publishing to channel: %s", config.REDIS_CHANNEL_FEATURES)

    dp = DataPipeline()
    broker = Broker()

    for batch in dp.stream():
        for payload in batch:
            instrument = payload["instrument"]
            # Strip large history arrays from the message for logging clarity
            log_payload = {k: v for k, v in payload.items() if not k.startswith("_")}
            log.info("Publishing features for %s", instrument)
            broker.publish(config.REDIS_CHANNEL_FEATURES, payload)
            log.debug("Payload (no history): %s", json.dumps(log_payload, indent=2))


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        log.info("Data Pipeline Service stopped by user.")
