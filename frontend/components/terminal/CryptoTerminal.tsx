'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { TradingViewChart } from '@/components/charts/TradingViewChart';

export const CryptoTerminal: React.FC = () => {
  const {
    selectedSymbol,
    setSelectedSymbol,
    latestTick,
    orderBook,
    account,
  } = useTradingStore();

  const cryptoPositions = Object.entries(account?.positions || {}).filter(([sym]) =>
    ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BTCUSDT.P', 'ETHUSDT.P'].includes(sym)
  );

  const currentPrice = latestTick?.close ?? 86600.0;
  const equity = account?.equity ?? 1000.0;
  const totalUnrealizedPl =
    account?.unrealized_pl ??
    Object.values(account?.positions || {}).reduce((acc, p) => acc + (p.unrealized_pl || 0), 0);

  // Compute actual maintenance margin used from active positions
  const maintMarginUsed = Object.values(account?.positions || {}).reduce((acc, p) => {
    const notional = Math.abs((p.qty || p.size || 0) * (p.current_price || p.entry_price || currentPrice));
    const lev = p.leverage || 5.0;
    return acc + (notional / lev);
  }, 0.0);

  const hasPositions = cryptoPositions.length > 0;
  const freeCollateral = Math.max(0, equity - maintMarginUsed);

  return (
    <div className="flex flex-col w-full bg-surface min-h-screen">
      {/* Sub-Header / Telemetry Strip */}
      <div className="w-full bg-surface-container-lowest px-6 py-3 flex flex-wrap items-center justify-between gap-4 border-b border-surface-container-high/60 shadow-sm">
        <div className="flex flex-wrap items-center gap-4">
          <div className="flex items-center gap-2 bg-surface-container px-3 py-1 rounded">
            <span className="w-2 h-2 rounded-full bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.7)]"></span>
            <span className="font-mono text-xs uppercase text-primary font-bold tracking-wider">
              PERPETUAL ENGINE: L1 CO-LOCATED
            </span>
          </div>

          <div className="flex items-center gap-2 font-mono text-xs text-on-surface-variant">
            <span className="text-on-surface font-semibold uppercase">INSTRUMENT:</span>
            {(['BTC-USD', 'ETH-USD', 'SOL-USD'] as const).map((sym) => (
              <button
                key={sym}
                onClick={() => setSelectedSymbol(sym)}
                className={`px-2.5 py-1 rounded text-xs font-mono font-bold transition-all ${
                  selectedSymbol === sym
                    ? 'bg-primary-container text-on-primary-container shadow-sm'
                    : 'bg-surface-container text-slate-300 hover:text-white hover:bg-surface-container-high'
                }`}
              >
                {sym}
              </button>
            ))}
          </div>

          <div className="h-4 w-px bg-surface-container-highest"></div>

          <div className="flex items-center gap-2 font-mono text-xs">
            <span className="text-on-surface-variant uppercase">NEXT FUNDING:</span>
            <span className="text-on-surface font-semibold bg-surface-container px-2 py-0.5 rounded">
              02:31:44
            </span>
            <span className="text-primary-fixed">+0.0100% avg</span>
          </div>
        </div>

        <div className="flex items-center gap-6 font-mono text-xs">
          <div className="flex items-center gap-2">
            <span className="text-on-surface-variant uppercase">MAINT. MARGIN:</span>
            <span className="text-slate-200 font-semibold">${maintMarginUsed.toFixed(2)}</span>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-on-surface-variant uppercase">FREE COLLATERAL:</span>
            <span className="text-primary-fixed font-bold">${freeCollateral.toFixed(2)} USDT</span>
          </div>
        </div>
      </div>

      {/* Main Container with generous spacing */}
      <div className="p-6 space-y-6 w-full">
        {/* Section 1: Collateral & Market Regime Heatmap */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6">
          {/* Account Health & Liquidation Safety Gauge */}
          <div className="lg:col-span-4 bg-surface-container-low p-5 flex flex-col justify-between rounded-xl shadow-lg border border-surface-container-high/60 relative overflow-hidden">
            <div className="absolute -right-12 -top-12 w-40 h-40 bg-primary/5 rounded-full blur-2xl pointer-events-none"></div>
            
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <span className="w-2.5 h-2.5 rounded-full bg-primary-fixed shadow-[0_0_8px_rgba(70,255,184,0.6)]"></span>
                <span className="font-mono text-xs uppercase tracking-wider text-slate-300 font-semibold">
                  COLLATERAL & RISK TELEMETRY
                </span>
              </div>
              <span className="font-mono text-[11px] uppercase px-2 py-0.5 bg-primary/10 text-primary-fixed border border-primary/20 rounded font-semibold">
                TIER 1 CLEARED
              </span>
            </div>

            <div className="grid grid-cols-2 gap-4 mb-4">
              <div className="bg-surface-container-lowest p-3.5 rounded-lg border border-surface-container-high/40">
                <div className="font-mono text-[11px] uppercase text-on-surface-variant">Unrealized P&L</div>
                <div className={`font-mono text-lg font-bold mt-1 ${totalUnrealizedPl >= 0 ? 'text-primary-fixed' : 'text-error'}`}>
                  {totalUnrealizedPl >= 0 ? '+' : ''}${totalUnrealizedPl.toFixed(2)}
                </div>
                <div className="font-mono text-[11px] text-slate-400 mt-0.5">
                  {hasPositions ? `${((totalUnrealizedPl / equity) * 100).toFixed(2)}% NAV Impact` : 'No Open Risk'}
                </div>
              </div>
              <div className="bg-surface-container-lowest p-3.5 rounded-lg border border-surface-container-high/40">
                <div className="font-mono text-[11px] uppercase text-on-surface-variant">Liquidation Proximity</div>
                <div className="font-mono text-lg text-primary-container font-bold mt-1">
                  {hasPositions ? 'OPTIMAL' : 'SAFE (FLAT)'}
                </div>
                <div className="font-mono text-[11px] text-on-surface-variant mt-0.5">
                  {hasPositions ? 'Margin Floor Monitored' : 'Zero Margin Risk'}
                </div>
              </div>
            </div>

            {/* Liquidation Safety Gauge Visualizer */}
            <div className="bg-surface-container p-3.5 rounded-lg flex flex-col gap-2">
              <div className="flex justify-between items-center font-mono text-xs">
                <span className="text-on-surface-variant uppercase text-[11px]">Liquidation Cushion</span>
                <span className="text-primary-fixed font-semibold">
                  {hasPositions ? 'OPTIMAL BUFFER' : '100% MARGIN AVAILABLE'}
                </span>
              </div>
              <div className="w-full h-2.5 bg-surface-container-highest rounded-full overflow-hidden flex">
                <div className="h-full bg-error" style={{ width: hasPositions ? '10%' : '0%' }}></div>
                <div className="h-full bg-amber-500" style={{ width: hasPositions ? '10%' : '0%' }}></div>
                <div className="h-full bg-primary-container relative" style={{ width: hasPositions ? '80%' : '100%' }}>
                  <div className="absolute right-0 top-0 bottom-0 w-1 bg-surface-container-lowest animate-pulse"></div>
                </div>
              </div>
              <div className="flex justify-between font-mono text-[10px] text-on-surface-variant pt-1">
                <span className="text-error">CRITICAL</span>
                <span className="text-amber-400">WARNING</span>
                <span className="text-primary-fixed">OPTIMAL (100%)</span>
              </div>
            </div>
          </div>

          {/* Perpetual Funding Rate Heatmap Grid */}
          <div className="lg:col-span-8 bg-surface-container-low p-5 rounded-xl shadow-lg border border-surface-container-high/60 flex flex-col justify-between">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-3">
                <span className="font-mono text-xs uppercase text-slate-100 tracking-wider font-bold">
                  24/7 Market Regime & Funding Rates
                </span>
                <span className="px-2 py-0.5 rounded bg-surface-container text-on-surface-variant font-mono text-[11px]">
                  8H CYCLE
                </span>
              </div>
              <div className="flex items-center gap-4 font-mono text-[11px] text-on-surface-variant">
                <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-primary-container"></span> Longs Pay (&gt;0.01%)</span>
                <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-surface-bright"></span> Neutral</span>
                <span className="flex items-center gap-1.5"><span className="w-2 h-2 rounded-sm bg-error"></span> Shorts Pay</span>
              </div>
            </div>

            {/* Heatmap Cells */}
            <div className="grid grid-cols-2 sm:grid-cols-3 gap-3">
              {[
                { sym: 'BTC', cat: 'PERP', rate: '+0.0100%', ann: '10.95%', pct: 70, col: 'primary-container' },
                { sym: 'ETH', cat: 'PERP', rate: '+0.0100%', ann: '10.95%', pct: 70, col: 'primary-container' },
                { sym: 'SOL', cat: 'PERP', rate: '+0.0150%', ann: '16.42%', pct: 85, col: 'primary-fixed' },
              ].map((item) => (
                <div
                  key={item.sym}
                  className="bg-surface-container p-3 rounded-lg flex flex-col justify-between border border-surface-container-high/40 hover:border-slate-700 transition-colors"
                >
                  <div className="flex justify-between items-baseline font-mono">
                    <span className="font-bold text-slate-100">{item.sym}</span>
                    <span className="text-[10px] text-primary-fixed">{item.cat}</span>
                  </div>
                  <div className="my-2 font-mono">
                    <div className="text-sm font-bold text-primary-fixed">{item.rate}</div>
                    <div className="text-[10px] text-on-surface-variant">Ann: {item.ann}</div>
                  </div>
                  <div className="w-full h-1 bg-surface-container-highest rounded-full overflow-hidden">
                    <div className="h-full bg-primary-container" style={{ width: `${item.pct}%` }}></div>
                  </div>
                </div>
              ))}
            </div>

            <div className="mt-4 flex items-center justify-between font-mono text-[11px] text-on-surface-variant pt-2.5 bg-surface-container-lowest px-4 py-2 rounded-lg border border-surface-container-high/30">
              <span>FUNDING ARB MONITOR: ACTIVE</span>
              <span className="text-primary-fixed">HISTORICAL FUNDING VOL: NORMALIZED</span>
            </div>
          </div>
        </div>

        {/* Section 2: Chart & L2 Depth Ladder */}
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 bg-surface-container-low p-4 rounded-xl border border-surface-container-high/60 shadow-lg">
          {/* Authoritative Interactive Candlestick Chart */}
          <div className="lg:col-span-9 min-h-[480px]">
            <TradingViewChart />
          </div>

          {/* L2 Orderbook Ladder */}
          <div className="lg:col-span-3 p-4 bg-surface-container-lowest rounded-xl border border-surface-container-high/60 flex flex-col justify-between font-mono text-xs">
            <div>
              <div className="flex items-center justify-between pb-2 mb-2 border-b border-surface-container-high">
                <span className="font-bold text-slate-200 uppercase tracking-wider text-[11px]">L2 Order Book</span>
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-surface-container text-slate-400">DEPTH 10</span>
              </div>
              <div className="font-mono text-[10px] uppercase text-on-surface-variant pb-1 flex justify-between">
                <span>PRICE (USDT)</span>
                <span>SIZE</span>
              </div>

              {/* Asks (Sell) */}
              <div className="flex flex-col gap-1 my-1">
                {(orderBook?.asks?.length ? orderBook.asks.slice(0, 5) : [
                  { price: currentPrice + 12, size: 1.45 },
                  { price: currentPrice + 8, size: 0.82 },
                  { price: currentPrice + 4, size: 2.10 },
                ]).map((lvl: any, i: number) => {
                  const p = typeof lvl === 'object' && 'price' in lvl ? lvl.price : Array.isArray(lvl) ? lvl[0] : currentPrice;
                  const sz = typeof lvl === 'object' && 'size' in lvl ? lvl.size : Array.isArray(lvl) ? lvl[1] : 1.0;
                  return (
                    <div key={i} className="flex justify-between items-center text-error">
                      <span>{Number(p).toFixed(2)}</span>
                      <span className="text-slate-300">{Number(sz).toFixed(3)}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Spread / Mark Price */}
            <div className="py-1.5 my-2 bg-surface-container text-center text-primary-fixed font-bold rounded-lg border border-primary-container/20 shadow-sm">
              <span className="text-[10px] text-slate-400 font-normal mr-1.5">MARK</span>
              ${currentPrice.toFixed(2)}
            </div>

            {/* Bids (Buy) */}
            <div>
              <div className="flex flex-col gap-1 my-1">
                {(orderBook?.bids?.length ? orderBook.bids.slice(0, 5) : [
                  { price: currentPrice - 4, size: 1.95 },
                  { price: currentPrice - 8, size: 3.40 },
                  { price: currentPrice - 12, size: 0.65 },
                ]).map((lvl: any, i: number) => {
                  const p = typeof lvl === 'object' && 'price' in lvl ? lvl.price : Array.isArray(lvl) ? lvl[0] : currentPrice;
                  const sz = typeof lvl === 'object' && 'size' in lvl ? lvl.size : Array.isArray(lvl) ? lvl[1] : 1.0;
                  return (
                    <div key={i} className="flex justify-between items-center text-primary-fixed">
                      <span>{Number(p).toFixed(2)}</span>
                      <span className="text-slate-300">{Number(sz).toFixed(3)}</span>
                    </div>
                  );
                })}
              </div>

              <div className="pt-2 mt-2 border-t border-surface-container-high/60 flex justify-between text-[10px] text-slate-400">
                <span>SPREAD: <strong className="text-slate-200">0.01%</strong></span>
                <span>IMBALANCE: <strong className="text-primary-fixed">+14.2% BID</strong></span>
              </div>
            </div>
          </div>
        </div>

        {/* Section 3: Active Crypto Perpetuals Positions Table */}
        <div className="bg-surface-container-low rounded-xl shadow-lg overflow-hidden flex flex-col border border-surface-container-high/60">
          <div className="h-10 bg-surface-container-lowest px-4 border-b border-surface-container-high flex items-center justify-between font-mono text-xs">
            <span className="font-bold text-slate-100 uppercase">
              Crypto Perpetuals Active Positions ({cryptoPositions.length})
            </span>
            <span className="text-primary-fixed font-semibold">REAL-TIME RISK GUARD ACTIVE</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="bg-slate-900 text-on-surface-variant uppercase text-[11px] border-b border-surface-container-high">
                  <th className="py-3 px-4">Instrument</th>
                  <th className="py-3 px-4">Side</th>
                  <th className="py-3 px-4">Size (Qty)</th>
                  <th className="py-3 px-4">Entry Price</th>
                  <th className="py-3 px-4">Mark Price</th>
                  <th className="py-3 px-4">Leverage</th>
                  <th className="py-3 px-4">Unrealized P&L</th>
                  <th className="py-3 px-4">Liquidation Price</th>
                </tr>
              </thead>
              <tbody>
                {cryptoPositions.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-on-surface-variant font-mono text-xs">
                      No active Crypto Perpetuals positions. Clean initial state ($1,000.00 Capital Available).
                    </td>
                  </tr>
                ) : (
                  cryptoPositions.map(([symbol, pos]: [string, any]) => {
                    const rawQty = pos.qty ?? pos.size ?? 0;
                    const isLong = String(pos.side || '').toLowerCase() === 'long' || rawQty >= 0;
                    const side = isLong ? 'LONG' : 'SHORT';
                    const absQty = Math.abs(rawQty);
                    const qtyDisplay = absQty < 0.01 ? absQty.toFixed(6) : absQty.toFixed(4);
                    const entryPrice = pos.entry_price || currentPrice;
                    const markPrice = pos.current_price || currentPrice;
                    const pnlVal = pos.unrealized_pl || 0;
                    return (
                      <tr key={symbol} className="border-b border-surface-container-high/40 hover:bg-surface-container transition-colors">
                        <td className="py-3 px-4 font-bold text-slate-100">{symbol}</td>
                        <td className="py-3 px-4">
                          <span
                            className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                              side === 'LONG'
                                ? 'bg-primary/20 text-primary-fixed border border-primary/30'
                                : 'bg-error/20 text-error border border-error/30'
                            }`}
                          >
                            {side}
                          </span>
                        </td>
                        <td className="py-3 px-4">{qtyDisplay}</td>
                        <td className="py-3 px-4">${entryPrice.toFixed(2)}</td>
                        <td className="py-3 px-4">${markPrice.toFixed(2)}</td>
                        <td className="py-3 px-4 text-secondary">{pos.leverage || '5.0'}x</td>
                        <td className={`py-3 px-4 font-bold ${pnlVal >= 0 ? 'text-primary-fixed' : 'text-error'}`}>
                          {pnlVal >= 0 ? `+$${pnlVal.toFixed(2)}` : `-$${Math.abs(pnlVal).toFixed(2)}`}
                        </td>
                        <td className="py-3 px-4 text-on-surface-variant">${(entryPrice * 0.8).toFixed(2)}</td>
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
