import { create } from 'zustand';
import { AccountState, Instrument, MLSignal, OHLCV, OrderBook, OrderExecution, SystemLog } from '@/types/trading';

interface TradingStoreState {
  selectedSymbol: Instrument;
  connectionStatus: 'CONNECTED' | 'DISCONNECTED' | 'RECONNECTING';
  engineStatus: 'RUNNING' | 'PAUSED' | 'HALTED';
  latencyMs: number;

  latestTick: OHLCV | null;
  historicalCandles: OHLCV[];
  orderBook: OrderBook;
  account: AccountState;
  signals: MLSignal[];
  executions: OrderExecution[];
  logs: SystemLog[];
  equityCurve: { time: string; equity: number; pnl: number }[];
  quotaState: any;
  screenerTargets: any;
  marketSession: any;
  goalSummary: any;
  microstructure: {
    symbol: string;
    vpoc_price: number | null;
    vah: number | null;
    val: number | null;
    cvd_trend: number;
    flow_score: number;
    iff_available: boolean;
  };

  setSelectedSymbol: (symbol: Instrument) => void;
  setConnectionStatus: (status: TradingStoreState['connectionStatus']) => void;
  updateTick: (tick: OHLCV) => void;
  setHistoricalCandles: (candles: OHLCV[]) => void;
  updateOrderBook: (book: OrderBook) => void;
  updateAccount: (account: Partial<AccountState>) => void;
  addSignal: (signal: MLSignal) => void;
  addExecution: (execution: OrderExecution) => void;
  addLog: (log: SystemLog) => void;
  updateQuotaState: (quota: any) => void;
  updateScreenerTargets: (targets: any) => void;
  updateMicrostructure: (data: any) => void;
  updateMarketSession: (session: any) => void;
  updateGoalSummary: (goal: any) => void;
}

export const useTradingStore = create<TradingStoreState>((set) => ({
  selectedSymbol: 'BTC-USD',
  connectionStatus: 'DISCONNECTED',
  engineStatus: 'RUNNING',
  latencyMs: 65,

  latestTick: null,
  historicalCandles: [],
  orderBook: { bids: [], asks: [], spread: 0 },
  account: {
    equity: 1000.0,
    balance: 1000.0,
    realized_pl: 0.0,
    gross_buying_power: 10000.0,
    active_drawdown_pct: 0.0,
    positions: {},
  },
  signals: [],
  executions: [],
  logs: [
    {
      id: 'init_log',
      timestamp: Date.now() / 1000,
      level: 'INFO',
      message: 'TEDENG ML Dashboard state store initialized',
      source: 'ENGINE',
    },
  ],
  equityCurve: [
    { time: '10:00', equity: 1000, pnl: 0 },
    { time: '10:05', equity: 1002, pnl: 2 },
    { time: '10:10', equity: 998, pnl: -2 },
    { time: '10:15', equity: 1005, pnl: 5 },
    { time: '10:20', equity: 1012, pnl: 12 },
  ],
  quotaState: {
    crypto: { completed: 0, wins: 0, losses: 0, win_pnl: 0.0, loss_pnl: 0.0 },
    futures: { completed: 0, wins: 0, losses: 0, win_pnl: 0.0, loss_pnl: 0.0 }
  },
  screenerTargets: { long: 'PENDING', short: 'PENDING' },
  marketSession: {
    us: { is_open: false, session_name: 'CLOSED', rth_hours: '09:30 - 16:00 ET' },
    crypto: { is_open: true, session_name: '24/7', rth_hours: '24/7/365' },
    current_symbol: null
  },
  goalSummary: {
    monthly_target_usd: 100.0,
    monthly_pnl_usd: 0.0,
    monthly_pnl_pct: 0.0,
    crypto_trades_used: "0/20",
    stock_trades_used: "0/80",
    crypto_completed: 0,
    crypto_ceiling: 20,
    stock_completed: 0,
    stock_ceiling: 80,
    equity_current_usd: 1000.0,
    equity_peak_usd: 1000.0,
    current_drawdown_pct: 0.0,
    engine_paused: false,
    pause_reason: null
  },
  microstructure: {
    symbol: '',
    vpoc_price: null,
    vah: null,
    val: null,
    cvd_trend: 0,
    flow_score: 0,
    iff_available: false,
  },

  setSelectedSymbol: (symbol) => set({ selectedSymbol: symbol, historicalCandles: [] }),
  setConnectionStatus: (status) => set({ connectionStatus: status }),
  updateQuotaState: (quota) => set({ quotaState: quota }),
  updateScreenerTargets: (targets) => set({ screenerTargets: targets }),
  updateMicrostructure: (data) => set({ microstructure: data }),
  updateMarketSession: (session) => set({ marketSession: session }),
  updateGoalSummary: (goal) => set({ goalSummary: goal }),

  updateTick: (tick) =>
    set((state) => {
      const candles = [...state.historicalCandles];
      const lastCandle = candles[candles.length - 1];

      if (lastCandle && lastCandle.time === tick.time) {
        candles[candles.length - 1] = {
          ...lastCandle,
          high: Math.max(lastCandle.high, tick.high),
          low: Math.min(lastCandle.low, tick.low),
          close: tick.close,
          volume: lastCandle.volume + tick.volume,
        };
      } else {
        candles.push(tick);
        if (candles.length > 500) candles.shift();
      }

      return { latestTick: tick, historicalCandles: candles };
    }),

  setHistoricalCandles: (candles) => set({ historicalCandles: candles }),
  updateOrderBook: (book) => set({ orderBook: book }),
  updateAccount: (accountData) =>
    set((state) => {
      const updatedAccount = { ...state.account, ...accountData };
      const nowStr = new Date().toLocaleTimeString('en-IN', { hour12: false, timeZone: 'Asia/Kolkata' });
      const currentCurve = [...state.equityCurve];
      
      if (currentCurve.length === 0 || currentCurve[currentCurve.length - 1].time !== nowStr) {
        currentCurve.push({
          time: nowStr,
          equity: updatedAccount.equity || 1000,
          pnl: updatedAccount.realized_pl || 0,
        });
        if (currentCurve.length > 50) currentCurve.shift();
      }

      return { account: updatedAccount, equityCurve: currentCurve };
    }),

  addSignal: (signal) =>
    set((state) => {
      if (state.signals.some((s) => s.signal_id === signal.signal_id)) return state;
      return { signals: [signal, ...state.signals.slice(0, 99)] };
    }),

  addExecution: (execution) =>
    set((state) => {
      if (state.executions.some((e) => e.order_id === execution.order_id)) return state;
      return { executions: [execution, ...state.executions.slice(0, 99)] };
    }),

  addLog: (log) => set((state) => ({ logs: [log, ...state.logs.slice(0, 199)] })),
}));
