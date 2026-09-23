export type Instrument = string;

export interface OHLCV {
  time: number; // Unix timestamp in seconds
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface MLSignal {
  signal_id: string;
  timestamp_generated: number;
  instrument: Instrument;
  direction_magnitude: number;
  confidence_score: number;
  regime_flag: 'high_volatility' | 'trending_up' | 'low_volatility' | 'neutral';
  latency_ms: number;
  per_model: {
    ridge: number;
    xgb: number;
    lstm: number;
  };
  weights_used: {
    ridge: number;
    xgb: number;
    lstm: number;
  };
  ohlcv?: Omit<OHLCV, 'time'>;
}

export interface Position {
  instrument: Instrument;
  qty: number;
  entry_price: number;
  current_price: number;
  unrealized_pl: number;
  unrealized_plpc: number;
}

export interface AccountState {
  equity: number;
  balance: number;
  realized_pl: number;
  unrealized_pl?: number;
  gross_buying_power: number;
  active_drawdown_pct: number;
  positions: Record<string, Position>;
}

export interface OrderExecution {
  order_id: string;
  signal_id: string;
  instrument: Instrument;
  action: 'BUY' | 'SELL';
  order_type: 'MARKET' | 'LIMIT';
  portfolio_allocation_pct: number;
  confidence: number;
  timestamp_proposed: number;
  risk_state: 'APPROVED' | 'REJECTED';
  checks_passed?: string[];
  failed_check?: string;
  oms_state: 'SUBMITTED' | 'FILLED' | 'FAILED' | 'SKIPPED_BY_RISK';
  oms_detail?: string;
  notional_value?: number;
}

export interface OrderBookLevel {
  price: number;
  size: number;
  total: number;
}

export interface OrderBook {
  bids: OrderBookLevel[];
  asks: OrderBookLevel[];
  spread: number;
}

export interface SystemLog {
  id: string;
  timestamp: number;
  level: 'INFO' | 'WARN' | 'ERROR' | 'SUCCESS';
  message: string;
  source: 'ENGINE' | 'RISK_GUARD' | 'OMS' | 'ML_MODEL';
}
