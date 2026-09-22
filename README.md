# TEDENG — Algorithmic Trading Core Brain

A microservices-style **Prediction Engine** for algorithmic trading.

```
Raw Feed → [DP] → [PP] → [M1/M2/M3] → [MA] → [SS] → [MB] → Dashboard
```

## Architecture

| Layer | File | Description |
|---|---|---|
| **DP** | `data_pipeline/pipeline.py` | yfinance OHLCV + frac-diff, GARCH vol, RSI, OBI |
| **PP** | `brain/preprocessor.py` | Rolling Z-score normalisation + imputation |
| **M1** | `brain/models/ridge_model.py` | Ridge Regression (statistical baseline) |
| **M2** | `brain/models/xgb_model.py` | XGBoost (non-linear ML) |
| **M3** | `brain/models/lstm_model.py` | 2-layer LSTM (temporal sequence) |
| **MA** | `brain/meta_aggregator.py` | Regime-based dynamic weight blending |
| **SS** | `brain/signal_standardizer.py` | Canonical signal packet `{magnitude, confidence, ts}` |
| **MB** | `middleware/broker.py` | Redis Pub/Sub (auto-fallback to in-process queue) |
| **UI** | `services/run_dashboard.py` | Streamlit live prediction dashboard |

## Quick Start

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. (Optional) Start Redis
```bash
docker run -d -p 6379:6379 redis
# OR — if Redis is unavailable, the broker auto-falls back to in-process queue
```

### 3. Run services (three separate terminals)

**Terminal 1 — Data Pipeline**
```bash
python services/run_data_pipeline.py
```

**Terminal 2 — Core Brain**
```bash
python services/run_brain.py
```

**Terminal 3 — Dashboard**
```bash
streamlit run services/run_dashboard.py
```

### 4. Run tests
```bash
pytest tests/ -v
```

## Configuration

All parameters live in [`config.py`](config.py):

```python
INSTRUMENTS = ["BTC-USD", "ETH-USD", "AAPL", "SPY"]   # targets
POLL_INTERVAL_SECONDS = 30                              # data fetch cadence
LSTM_SEQ_LEN = 30                                       # LSTM window
REGIME_VOL_THRESHOLD_HIGH = 0.020                       # vol > this → high_vol
```

## Signal Packet Schema

```json
{
  "signal_id":           "sig_98a7f62b",
  "timestamp_generated": 1698245612.482,
  "instrument":          "BTC-USD",
  "direction_magnitude": 0.65,
  "confidence_score":    0.82,
  "regime_flag":         "high_volatility",
  "latency_ms":          77,
  "per_model":           {"ridge": 0.50, "xgb": 0.60, "lstm": 0.80},
  "weights_used":        {"ridge": 0.10, "xgb": 0.30, "lstm": 0.60}
}
```

## Latency Budget

| Stage | Target |
|---|---|
| DP → PP (feature delivery) | ~5 ms |
| PP → Ensemble models | ~20 ms |
| Ensemble → MA → SS | ~77 ms |
| SS → MB (publish) | ~2 ms |
| MB → consumer | ~3 ms |
| **Total** | **< 120 ms** |
