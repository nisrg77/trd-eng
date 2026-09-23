'use client';

import React, { useEffect } from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { TradingViewChart } from '@/components/charts/TradingViewChart';
import { InstrumentSelector } from '@/components/widgets/InstrumentSelector';
import { StockScreenerCard } from '@/components/widgets/StockScreenerCard';

export const UsFuturesTerminal: React.FC = () => {
  const {
    screenerTargets,
    marketSession,
    account,
    setSelectedSymbol,
    selectedSymbol,
  } = useTradingStore();

  // Auto-switch away from crypto symbols on mount if viewing US Futures Terminal
  useEffect(() => {
    const isCrypto = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BTCUSDT.P', 'ETHUSDT.P'].includes(selectedSymbol);
    if (isCrypto) {
      setSelectedSymbol('NVDA');
    }
  }, [selectedSymbol, setSelectedSymbol]);

  const stockPositions = Object.entries(account?.positions || {}).filter(([sym]) =>
    !['BTC-USD', 'ETH-USD', 'SOL-USD', 'BTCUSDT.P', 'ETHUSDT.P'].includes(sym)
  );

  const isRthOpen = marketSession?.us?.is_open ?? false;

  return (
    <div className="flex flex-col w-full bg-surface min-h-screen">
      {/* Top Header Banner: Market Session Status & Interactive US Stock Search */}
      <div className="w-full bg-surface-container-lowest px-4 py-2.5 flex flex-wrap items-center justify-between gap-4 border-b border-surface-container-high/60 shadow-sm">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2 bg-surface-container px-3 py-1 rounded">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                isRthOpen ? 'bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.7)]' : 'bg-amber-500'
              }`}
            ></span>
            <span className="font-label-xs text-xs uppercase text-on-surface font-bold tracking-wider">
              US EQUITIES RTH: {isRthOpen ? 'REGULAR SESSION OPEN' : 'CLOSED / OUT OF HOURS'}
            </span>
          </div>

          <div className="flex items-center gap-2 font-numeric-sm text-xs text-on-surface-variant">
            <span className="font-label-xs uppercase">RTH HOURS:</span>
            <span className="text-primary-fixed font-semibold">09:30 - 16:00 ET (MON-FRI)</span>
          </div>
        </div>

        {/* Interactive US Stock Search Bar */}
        <div className="flex items-center gap-4">
          <InstrumentSelector />
          <div className="hidden md:flex items-center gap-2 font-numeric-sm text-xs">
            <span className="font-label-xs uppercase text-on-surface-variant">MONTHLY CEILING:</span>
            <span className="text-primary-fixed font-bold">80 TRADES MAX</span>
          </div>
        </div>
      </div>

      {/* Section 1: 15-Minute TradingView Top Stock Screener Card */}
      <div className="p-3 bg-surface">
        <StockScreenerCard />
      </div>

      {/* Section 2: Major Index & Stock Metrics Quick Select Strip */}
      <div className="grid grid-cols-1 md:grid-cols-4 gap-3 p-3 bg-surface">
        {[
          { sym: 'NVDA', name: 'NVIDIA CORP', price: '$138.50', chg: '+1.85 (+1.35%)', rvol: '2.45x', positive: true },
          { sym: 'AAPL', name: 'APPLE INC', price: '$341.00', chg: '+2.10 (+0.62%)', rvol: '1.88x', positive: true },
          { sym: 'SPY', name: 'S&P 500 ETF', price: '$774.00', chg: '+4.12 (+0.54%)', rvol: '1.52x', positive: true },
          { sym: 'TSLA', name: 'TESLA INC', price: '$252.00', chg: '+3.20 (+1.28%)', rvol: '2.12x', positive: true },
        ].map((item) => (
          <div
            key={item.sym}
            onClick={() => setSelectedSymbol(item.sym as any)}
            className={`p-3 rounded-xl border transition-all cursor-pointer flex flex-col justify-between ${
              selectedSymbol === item.sym
                ? 'bg-slate-900 border-cyan-500 shadow-md shadow-cyan-500/20'
                : 'bg-surface-container-low border-surface-container-high hover:border-slate-700'
            }`}
          >
            <div className="flex justify-between items-center text-xs text-on-surface-variant font-mono">
              <span className="font-bold text-slate-200">{item.sym}</span>
              <span className="text-cyan-400 font-semibold">{item.name}</span>
            </div>
            <div className="my-1 flex items-baseline justify-between font-mono">
              <span className="text-xl font-bold text-slate-100">{item.price}</span>
              <span className={`text-xs font-semibold ${item.positive ? 'text-emerald-400' : 'text-rose-400'}`}>
                {item.chg}
              </span>
            </div>
            <div className="text-[11px] font-mono text-slate-400 flex justify-between">
              <span>RVOL: {item.rvol}</span>
              <span className="text-cyan-400 hover:underline">Select Chart →</span>
            </div>
          </div>
        ))}
      </div>

      {/* Section 3: Interactive TradingView Candle Chart */}
      <div className="p-3 bg-surface">
        <TradingViewChart />
      </div>

      {/* Section 4: Active US Futures Positions Table */}
      <div className="p-3 bg-surface">
        <div className="bg-surface-container-low rounded-xl shadow-lg overflow-hidden flex flex-col border border-surface-container-high/60">
          <div className="h-10 bg-surface-container-lowest px-4 border-b border-surface-container-high flex items-center justify-between text-numeric-sm font-mono">
            <span className="font-headline-sm text-slate-100 font-bold uppercase text-xs">
              US Stock Futures Active Positions ({stockPositions.length})
            </span>
            <span className="text-xs text-emerald-400 font-semibold">
              RTH SESSION ENGINE ACTIVE
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="bg-slate-900 text-slate-400 uppercase text-[11px] border-b border-slate-800">
                  <th className="py-2.5 px-4">Instrument</th>
                  <th className="py-2.5 px-4">Side</th>
                  <th className="py-2.5 px-4">Qty</th>
                  <th className="py-2.5 px-4">Entry Price</th>
                  <th className="py-2.5 px-4">Mark Price</th>
                  <th className="py-2.5 px-4">Dynamic Leverage</th>
                  <th className="py-2.5 px-4">Unrealized P&L</th>
                  <th className="py-2.5 px-4">Risk Budget</th>
                </tr>
              </thead>
              <tbody>
                {stockPositions.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-6 text-center text-slate-500 font-mono text-xs">
                      No active US Stock Futures positions currently held.
                    </td>
                  </tr>
                ) : (
                  stockPositions.map(([symbol, pos]: [string, any]) => {
                    const side = pos.qty > 0 ? 'LONG' : 'SHORT';
                    const entryPrice = pos.entry_price || 100.0;
                    const markPrice = pos.current_price || entryPrice;
                    const pnlVal = pos.unrealized_pl || 0;
                    return (
                      <tr key={symbol} className="border-b border-slate-800/40 hover:bg-slate-800/40">
                        <td className="py-3 px-4 font-bold text-slate-100">{symbol}</td>
                        <td className="py-3 px-4">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${side === 'LONG' ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30' : 'bg-rose-500/20 text-rose-400 border border-rose-500/30'}`}>
                            {side}
                          </span>
                        </td>
                        <td className="py-3 px-4">{Math.abs(pos.qty).toFixed(2)}</td>
                        <td className="py-3 px-4">${entryPrice.toFixed(2)}</td>
                        <td className="py-3 px-4">${markPrice.toFixed(2)}</td>
                        <td className="py-3 px-4 text-cyan-400">{pos.leverage || '10.0'}x</td>
                        <td className={`py-3 px-4 font-bold ${pnlVal >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                          {pnlVal >= 0 ? `+$${pnlVal.toFixed(2)}` : `-$${Math.abs(pnlVal).toFixed(2)}`}
                        </td>
                        <td className="py-3 px-4 text-slate-400">$10.00 Risk Cap</td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </div>
    </div>
  );
};
