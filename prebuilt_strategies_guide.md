# Prebuilt Trading Strategies: Best Frameworks & Ready-to-Run Repositories

If you do not want to code trading strategies from scratch, selecting frameworks with **large, active, battle-tested prebuilt strategy repositories** is essential. Below is the curated ranking of the best libraries and ecosystems with ready-to-run prebuilt strategies.

---

## 1. Top Frameworks Ranked by Prebuilt Strategy Ecosystem

```
┌─────────────────────────────────────────────────────────────────────────────┐
│ 1. FREQTRADE (freqtrade-strategies) ────► 200+ Production Crypto Strategies │
│ 2. HUMMINGBOT ──────────────────────────► Best Prebuilt Market Making & Arb │
│ 3. FINRL (FinRL-Meta) ──────────────────► Prebuilt DRL Trading Pipelines    │
│ 4. FASTQUANT ───────────────────────────► 1-Line Prebuilt Backtrader Strats │
│ 5. JESSE ───────────────────────────────► Modern Crypto Strategy Store      │
└─────────────────────────────────────────────────────────────────────────────┘
```

---

## 2. In-Depth Breakdown of Frameworks with Prebuilt Strategies

### #1. Freqtrade (`freqtrade-strategies` Repository)
* **Status**: **The Gold Standard for Prebuilt Crypto Strategies** (Over 200+ open-source strategies tested on Binance, Bybit, KuCoin, Kraken).
* **Official Repository**: `freqtrade/freqtrade-strategies` on GitHub.
* **Top Production-Proven Prebuilt Strategies**:
  1. **NostalgiaForInfinity (NFI / NFINext)**:
     - The most famous open-source crypto strategy in the world.
     - Combines multiple sub-strategies: EMA bounce, RSI dip buying, volume flow breakouts, volatility squeezes, and dynamic stop-loss protections.
     - Actively maintained by a massive quant community.
  2. **CombinedBinHAndCluc (BinH & Cluc)**:
     - Classic mean-reversion algorithm looking for panic sell dips below lower Bollinger Bands with high volume and quick RSI rebound.
  3. **SMAOffsetProtect / EMAOffset**:
     - Trend-following strategy with dynamic offset bands and emergency crash guards.
  4. **MultiRSI / BbandRsi**:
     - Multi-timeframe momentum and mean-reversion crossovers.
* **How to use them**:
  - Simply copy the `.py` strategy file into your `user_data/strategies/` folder.
  - Run backtest with 1 command: `freqtrade backtesting --strategy NostalgiaForInfinityX`

---

### #2. Hummingbot (Prebuilt Market Making & Arbitrage)
* **Status**: Best for **Prebuilt High-Frequency, Market Making & Arbitrage** (used by crypto hedge funds and market makers).
* **Prebuilt Out-of-the-Box Strategies**:
  1. **Pure Market Making (`pure_market_making`)**: Places dual-sided limit orders (bid/ask spreads) around the order book with automatic inventory skew and volatility adjustments.
  2. **Cross-Exchange Market Making**: Hedging limit orders on Exchange A with market orders on Exchange B.
  3. **Spot-Perpetual Funding Rate Arbitrage (Cash & Carry)**: Automatically buys spot and shorts perpetual futures to collect 10-30% APY funding rates with delta-neutral risk.
  4. **Triangular Arbitrage**: Capitalizes on price discrepancies between 3 pairs on the same exchange (e.g., BTC/USDT $\rightarrow$ ETH/BTC $\rightarrow$ ETH/USDT).
* **How to use them**:
  - Hummingbot provides an interactive CLI. Select strategy: `create --strategy pure_market_making`, configure spreads and size, and launch.

---

### #3. FinRL & FinRL-Meta (Prebuilt Reinforcement Learning Strategies)
* **Status**: Best for **Prebuilt AI/DRL Agents & Portfolio Allocation**.
* **Prebuilt Algorithms & Environments**:
  1. **Ensemble Strategy (`EnsembleAgent`)**:
     - Pre-trained ensemble combining PPO, A2C, and DDPG.
     - Automatically switches between agents based on rolling Sharpe ratio.
  2. **Stock Portfolio Allocation (`PortfolioAllocationEnv`)**:
     - Prebuilt environment for 30 Dow Jones / S&P 500 stocks that dynamically adjusts capital weights to maximize risk-adjusted returns.
  3. **Crypto DRL Trader (`CryptoTradingEnv`)**:
     - Pre-configured environment with Bitcoin / Ethereum historical features and reward functions.
* **How to use them**:
  - Uses standard tutorial notebooks and scripts inside the `FinRL-Tutorials` repository.

---

### #4. Fastquant (1-Line Prebuilt Backtrader Strategies)
* **Status**: Built directly on top of **Backtrader** for developers who want prebuilt strategies without writing Backtrader boilerplate.
* **Prebuilt Strategies Included**:
  - `smac`: Simple Moving Average Crossover
  - `emac`: Exponential Moving Average Crossover
  - `rsi`: Relative Strength Index oversold/overbought
  - `macd`: MACD signal crossover
  - `bbands`: Bollinger Bands mean-reversion
  - `buynhold`: Buy and Hold benchmark
  - `sentiment`: Combines Twitter/news sentiment scores with price
* **Code Example (Zero Boilerplate)**:
```python
from fastquant import backtest
import pandas as pd

# 1-line backtest of prebuilt RSI strategy on historical data
df = pd.read_csv("btc_daily.csv")
results = backtest("rsi", df, rsi_period=14, rsi_lower=30, rsi_upper=70)
print(results)
```

---

### #5. Jesse (`jesse-strategies`)
* **Status**: Modern Python crypto trading framework designed for usability and fast backtesting.
* **Prebuilt Community Strategies**:
  - Trend following strategies using Supertrend and Hull Moving Average (HMA).
  - DCA (Dollar Cost Averaging) dip-buying bots.
  - Volatility breakout strategies using Keltner Channels.

---

## 3. Comparison Matrix: Which Prebuilt Solution Fits TRDENG?

| Framework | Strategy Types Provided | Complexity | Quality of Prebuilt Code | Best For |
| :--- | :--- | :--- | :--- | :--- |
| **Freqtrade** | 200+ Spot/Futures Momentum, Mean Reversion, Breakout | Low (Plug & Play) | ⭐⭐⭐⭐⭐ (Battle-tested in real funds) | **Live Crypto Directional Trading** |
| **Hummingbot**| Pure Market Making, Funding Rate Arb, Triangular Arb | Medium | ⭐⭐⭐⭐⭐ (Institutional standard) | **Market Making & Delta-Neutral Yield** |
| **FinRL** | DRL Stock Allocation, DRL Crypto Agent, Ensemble | High | ⭐⭐⭐⭐ (Research & AI Allocation) | **AI-Driven Portfolio Weighting** |
| **Fastquant** | RSI, MACD, BBands, SMA, EMA, Sentiment | Lowest (1 Line) | ⭐⭐⭐ (Classical indicators) | **Instant Backtrader Prototyping** |

---

## 4. How to Plug Prebuilt Strategies into TRDENG Right Now

### Option A: The Freqtrade Route (Recommended for Crypto Perpetuals)
1. Install Freqtrade: `pip install freqtrade`
2. Clone the strategies repo:
   ```bash
   git clone https://github.com/freqtrade/freqtrade-strategies.git
   ```
3. Copy top strategies like `NostalgiaForInfinityX.py` or `CombinedBinHAndCluc.py` into your strategy directory.
4. Pass their buy/sell signals into TRDENG's [execution/engine.py](file:///d:/New%20folder/TRDENG/execution/engine.py) to apply TRDENG's 9-layer risk gating and monthly loss caps!

### Option B: The Fastquant Route (If you want Backtrader)
1. Install Fastquant: `pip install fastquant`
2. Test any standard strategy (RSI, MACD, BBands) on your dataset with 1 line of Python.
