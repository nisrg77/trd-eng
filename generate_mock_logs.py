import json
import random
from datetime import datetime, timedelta

def generate_mock_logs():
    strategies = ["Crypto Momentum", "US Equities ORB", "Funding Rate Arb"]
    symbols = ["BTC/USDT", "ETH/USDT", "AAPL", "TSLA"]
    
    with open("intent_trace_example.log", "w") as f:
        current_time = datetime.now()
        
        # Generate 100 log events, each mapping an intent through layers
        for i in range(1, 101):
            intent_id = f"trd_{random.randint(1000, 9999)}_{i}"
            symbol = random.choice(symbols)
            strategy = random.choice(strategies)
            intent_type = random.choice(["ENTRY", "EXIT", "SCALE"])
            
            # Layer 1: Feature Engine
            f.write(f"[{current_time.isoformat()}] [L1_FEATURE] In: aggTrade {symbol} | Out: Features MAvg, RSI, Volatility\n")
            current_time += timedelta(milliseconds=random.randint(1, 5))
            
            # Layer 2: Strategy Sleeve
            f.write(f"[{current_time.isoformat()}] [L2_STRATEGY] In: Features, PosContext=0 | Out: OrderIntent(id={intent_id}, type={intent_type}, sym={symbol}, strat={strategy})\n")
            current_time += timedelta(milliseconds=random.randint(1, 10))
            
            # Layer 3: Validation & Regime
            # Randomly drop some intents due to regime
            if random.random() < 0.15:
                f.write(f"[{current_time.isoformat()}] [L3_VALIDATOR] In: OrderIntent({intent_id}) | Out: DROPPED (Reason: Regime Muted for {strategy})\n")
                current_time += timedelta(seconds=random.randint(1, 5))
                continue
            else:
                f.write(f"[{current_time.isoformat()}] [L3_VALIDATOR] In: OrderIntent({intent_id}) | Out: Validated OrderIntent({intent_id})\n")
            current_time += timedelta(milliseconds=random.randint(1, 5))
            
            # Layer 4: Risk Guard
            if random.random() < 0.1:
                f.write(f"[{current_time.isoformat()}] [L4_RISK_GUARD] In: Validated OrderIntent({intent_id}) | Out: BLOCKED (Reason: Max Position Size Exceeded)\n")
                current_time += timedelta(seconds=random.randint(1, 5))
                continue
            else:
                f.write(f"[{current_time.isoformat()}] [L4_RISK_GUARD] In: Validated OrderIntent({intent_id}) | Out: Approved OrderIntent({intent_id})\n")
            current_time += timedelta(milliseconds=random.randint(1, 5))
            
            # Layer 5: Execution Core
            f.write(f"[{current_time.isoformat()}] [L5_EXECUTION] In: Approved OrderIntent({intent_id}) | Out: clOrdId={intent_id}_exec, State=SUBMITTED\n")
            current_time += timedelta(milliseconds=random.randint(10, 50))
            
            # Layer 6: Telemetry
            f.write(f"[{current_time.isoformat()}] [L6_TELEMETRY] In: State=FILLED for clOrdId={intent_id}_exec | Out: Broadcast to /ws/trading, Saved DB\n")
            f.write("-" * 80 + "\n")
            current_time += timedelta(seconds=random.randint(1, 10))

if __name__ == '__main__':
    generate_mock_logs()
    print("Mock logs generated in intent_trace_example.log")
