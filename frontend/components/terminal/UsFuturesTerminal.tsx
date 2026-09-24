'use client';

import React, { useEffect } from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { TradingViewChart } from '@/components/charts/TradingViewChart';
import { InstrumentSelector } from '@/components/widgets/InstrumentSelector';
import { StockScreenerCard } from '@/components/widgets/StockScreenerCard';

export const UsFuturesTerminal: React.FC = () => {
  const {
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
      <div className="w-full bg-surface-container-lowest px-6 py-3 flex flex-wrap items-center justify-between gap-4 border-b border-surface-container-high/60 shadow-sm">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2 bg-surface-container px-3 py-1 rounded">
            <span
              className={`w-2.5 h-2.5 rounded-full ${
                isRthOpen ? 'bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.7)]' : 'bg-amber-500'
              }`}
            ></span>
            <span className="font-mono text-xs uppercase text-slate-100 font-bold tracking-wider">
              US EQUITIES RTH: {isRthOpen ? 'REGULAR SESSION OPEN' : 'CLOSED / OUT OF HOURS'}
            </span>
          </div>

          <div className="flex items-center gap-2 font-mono text-xs text-on-surface-variant">
            <span className="uppercase text-[11px]">RTH HOURS:</span>
            <span className="text-primary-fixed font-semibold">09:30 - 16:00 ET (MON-FRI)</span>
          </div>
        </div>

        {/* Interactive US Stock Search Bar */}
        <div className="flex items-center gap-6">
          <InstrumentSelector />
          <div className="hidden md:flex items-center gap-2 font-mono text-xs">
            <span className="uppercase text-on-surface-variant text-[11px]">DAILY CEILING:</span>
            <span className="text-primary-fixed font-bold">80 TRADES/DAY</span>
          </div>
        </div>
      </div>

      {/* Main Content Area with generous spacing */}
      <div className="p-6 space-y-6 w-full">
        {/* Section 1: 15-Minute TradingView Top Stock Screener Card */}
        <div className="w-full">
          <StockScreenerCard />
        </div>

        {/* Section 2: Interactive Candlestick Chart */}
        <div className="w-full min-h-[480px]">
          <TradingViewChart />
        </div>

        {/* Section 3: Active US Futures Positions Table */}
        <div className="bg-surface-container-low rounded-xl shadow-lg overflow-hidden flex flex-col border border-surface-container-high/60">
          <div className="h-10 bg-surface-container-lowest px-4 border-b border-surface-container-high flex items-center justify-between font-mono text-xs">
            <span className="font-bold text-slate-100 uppercase">
              US Stock Futures Active Positions ({stockPositions.length})
            </span>
            <span className="text-emerald-400 font-semibold">
              RTH SESSION ENGINE ACTIVE
            </span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="bg-slate-900 text-slate-400 uppercase text-[11px] border-b border-slate-800">
                  <th className="py-3 px-4">Instrument</th>
                  <th className="py-3 px-4">Side</th>
                  <th className="py-3 px-4">Qty</th>
                  <th className="py-3 px-4">Entry Price</th>
                  <th className="py-3 px-4">Mark Price</th>
                  <th className="py-3 px-4">Dynamic Leverage</th>
                  <th className="py-3 px-4">Unrealized P&L</th>
                  <th className="py-3 px-4">Risk Budget</th>
                </tr>
              </thead>
              <tbody>
                {stockPositions.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-slate-500 font-mono text-xs">
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
                      <tr key={symbol} className="border-b border-slate-800/40 hover:bg-slate-800/40 transition-colors">
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
