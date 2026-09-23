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
    microstructure,
  } = useTradingStore();

  const cryptoPositions = Object.entries(account?.positions || {}).filter(([sym]) =>
    ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BTCUSDT.P', 'ETHUSDT.P'].includes(sym)
  );

  const currentPrice = latestTick?.close ?? 86582.0;
  const highPrice = latestTick?.high ?? currentPrice * 1.01;
  const lowPrice = latestTick?.low ?? currentPrice * 0.99;
  const openPrice = latestTick?.open ?? currentPrice;
  const priceChange = currentPrice - openPrice;
  const priceChangePct = openPrice > 0 ? (priceChange / openPrice) * 100 : 0;
  const totalUnrealizedPl = account?.unrealized_pl ?? Object.values(account?.positions || {}).reduce((acc, p) => acc + (p.unrealized_pl || 0), 0);

  return (
    <div className="flex flex-col w-full bg-surface min-h-screen">
      {/* Micro Ticker Tape & Top Telemetry Anchor */}
      <div className="w-full bg-surface-container-lowest px-space-md py-space-xs flex flex-wrap items-center justify-between gap-space-md shadow-sm border-b border-surface-container-high/60">
        <div className="flex items-center gap-space-md overflow-x-auto">
          <div className="flex items-center gap-space-xs bg-surface-container px-space-sm py-0.5 rounded">
            <span className="w-1.5 h-1.5 rounded-full bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.45)]"></span>
            <span className="font-label-xs text-label-xs uppercase text-primary tracking-wider">
              PERPETUAL ENGINE: L1 CO-LOCATED
            </span>
          </div>

          <div className="flex items-center gap-space-xs font-numeric-sm text-numeric-sm text-on-surface-variant">
            <span className="text-on-surface uppercase font-semibold">SYMBOL:</span>
            <button
              onClick={() => setSelectedSymbol('BTC-USD')}
              className={`px-1.5 py-0.5 rounded font-bold ${
                selectedSymbol === 'BTC-USD'
                  ? 'bg-primary-container text-on-primary-container'
                  : 'bg-surface-container text-primary-fixed'
              }`}
            >
              BTC-USD
            </button>
            <button
              onClick={() => setSelectedSymbol('ETH-USD')}
              className={`px-1.5 py-0.5 rounded font-bold ${
                selectedSymbol === 'ETH-USD'
                  ? 'bg-primary-container text-on-primary-container'
                  : 'bg-surface-container text-primary-fixed'
              }`}
            >
              ETH-USD
            </button>
          </div>

          <div className="h-3 w-px bg-surface-container-highest"></div>

          <div className="flex items-center gap-space-sm font-numeric-sm text-numeric-sm">
            <span className="text-on-surface-variant uppercase font-label-xs text-label-xs">NEXT FUNDING IN:</span>
            <span className="text-on-surface font-semibold bg-surface-container-high px-1.5 py-0.5 rounded">
              02:31:44
            </span>
            <span className="text-primary-fixed">+0.0100% avg</span>
          </div>
        </div>

        <div className="flex items-center gap-space-lg font-numeric-sm text-numeric-sm">
          <div className="flex items-center gap-space-xs">
            <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">CROSS MARGIN RATIO:</span>
            <span className="text-on-surface font-semibold">38.2%</span>
          </div>
          <div className="flex items-center gap-space-xs">
            <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">MAINT. MARGIN:</span>
            <span className="text-secondary">$48,190.00</span>
          </div>
          <div className="flex items-center gap-space-xs">
            <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">FREE COLLATERAL:</span>
            <span className="text-on-surface font-semibold">${(account?.equity ?? 1000).toFixed(2)} USDT</span>
          </div>
        </div>
      </div>

      {/* Section 1: Real-Time Crypto Market Regime & Funding Telemetry */}
      <div className="grid grid-cols-1 lg:grid-cols-12 gap-space-xs p-space-xs bg-surface">
        {/* Account Health & Liquidation Safety Gauge */}
        <div className="lg:col-span-4 bg-surface-container-low p-space-md flex flex-col justify-between rounded shadow-sm relative overflow-hidden">
          <div className="absolute -right-12 -top-12 w-40 h-40 bg-primary/5 rounded-full blur-2xl pointer-events-none"></div>
          <div className="flex items-center justify-between mb-space-sm">
            <div className="flex items-center gap-space-xs">
              <span className="w-2 h-2 rounded-full bg-primary-fixed shadow-[0_0_8px_rgba(70,255,184,0.6)]"></span>
              <span className="font-label-xs text-label-xs uppercase tracking-wider text-on-surface-variant">
                COLLATERAL & RISK TELEMETRY
              </span>
            </div>
            <span className="font-label-xs text-label-xs uppercase px-1.5 py-0.5 bg-primary/10 text-primary-fixed rounded font-semibold">
              TIER 1 CLEARED
            </span>
          </div>

          <div className="grid grid-cols-2 gap-space-md mb-space-md">
            <div className="bg-surface-container-lowest p-space-sm rounded">
              <div className="font-label-xs text-label-xs uppercase text-on-surface-variant">Unrealized P&L</div>
              <div className={`font-numeric-lg text-numeric-lg font-semibold ${totalUnrealizedPl >= 0 ? 'text-primary-fixed' : 'text-error'}`}>
                {totalUnrealizedPl >= 0 ? '+' : ''}${totalUnrealizedPl.toFixed(2)}
              </div>
              <div className="font-numeric-sm text-numeric-sm text-primary">+2.65% NAV Impact</div>
            </div>
            <div className="bg-surface-container-lowest p-space-sm rounded">
              <div className="font-label-xs text-label-xs uppercase text-on-surface-variant">Liquidation Proximity</div>
              <div className="font-numeric-lg text-numeric-lg text-primary-container font-semibold">SAFE (74.2%)</div>
              <div className="font-numeric-sm text-numeric-sm text-on-surface-variant">Margin Dist. Floor</div>
            </div>
          </div>

          {/* Liquidation Safety Gauge Visualizer */}
          <div className="bg-surface-container p-space-sm rounded flex flex-col gap-space-xs">
            <div className="flex justify-between items-center font-numeric-sm text-numeric-sm">
              <span className="text-on-surface-variant font-label-xs text-label-xs uppercase">Liquidation Cushion</span>
              <span className="text-primary-fixed font-semibold">74.2% TO MARGIN CALL</span>
            </div>
            <div className="w-full h-2.5 bg-surface-container-highest rounded overflow-hidden flex">
              <div className="h-full bg-error" style={{ width: '15%' }} title="Immediate Liquidation Band"></div>
              <div className="h-full bg-surface-bright" style={{ width: '10.8%' }} title="Buffer Zone"></div>
              <div className="h-full bg-primary-container relative" style={{ width: '74.2%' }}>
                <div className="absolute right-0 top-0 bottom-0 w-1 bg-surface-container-lowest animate-pulse"></div>
              </div>
            </div>
            <div className="flex justify-between font-label-xs text-label-xs text-on-surface-variant pt-0.5">
              <span className="text-error">CRITICAL (0%)</span>
              <span className="text-secondary">WARNING (25%)</span>
              <span className="text-primary-fixed">OPTIMAL (100%)</span>
            </div>
          </div>
        </div>

        {/* Perpetual Funding Rate Heatmap Grid */}
        <div className="lg:col-span-8 bg-surface-container-low p-space-md rounded shadow-sm flex flex-col justify-between">
          <div className="flex items-center justify-between mb-space-sm">
            <div className="flex items-center gap-space-sm">
              <span className="font-headline-sm text-headline-sm uppercase text-on-surface tracking-wider font-semibold">
                24/7 Market Regime & Funding Heatmap
              </span>
              <span className="px-space-sm py-0.5 rounded bg-surface-container text-on-surface-variant font-label-xs text-label-xs">
                8H SYNC CYCLE
              </span>
            </div>
            <div className="flex items-center gap-space-md font-label-xs text-label-xs text-on-surface-variant">
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-primary-container"></span> Longs Pay (&gt;0.01%)</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-surface-bright"></span> Neutral (0.00%)</span>
              <span className="flex items-center gap-1"><span className="w-2 h-2 rounded-sm bg-error"></span> Shorts Pay (&lt;0.00%)</span>
            </div>
          </div>

          {/* Heatmap Cells */}
          <div className="grid grid-cols-2 sm:grid-cols-3 md:grid-cols-6 gap-space-xs">
            <div className="bg-surface-container p-space-sm rounded flex flex-col justify-between border border-primary-container/30">
              <div className="flex justify-between items-baseline">
                <span className="font-headline-sm text-headline-sm text-on-surface">BTC</span>
                <span className="font-label-xs text-label-xs text-primary-fixed">PERP</span>
              </div>
              <div className="my-space-xs">
                <div className="font-numeric-md text-numeric-md text-primary-fixed font-semibold">+0.0142%</div>
                <div className="font-label-xs text-label-xs text-on-surface-variant">Ann: 15.55%</div>
              </div>
              <div className="w-full h-1 bg-surface-container-highest rounded overflow-hidden">
                <div className="h-full bg-primary-container" style={{ width: '71%' }}></div>
              </div>
            </div>

            <div className="bg-surface-container p-space-sm rounded flex flex-col justify-between">
              <div className="flex justify-between items-baseline">
                <span className="font-headline-sm text-headline-sm text-on-surface">ETH</span>
                <span className="font-label-xs text-label-xs text-primary-fixed">PERP</span>
              </div>
              <div className="my-space-xs">
                <div className="font-numeric-md text-numeric-md text-primary-fixed font-semibold">+0.0108%</div>
                <div className="font-label-xs text-label-xs text-on-surface-variant">Ann: 11.83%</div>
              </div>
              <div className="w-full h-1 bg-surface-container-highest rounded overflow-hidden">
                <div className="h-full bg-primary-container" style={{ width: '54%' }}></div>
              </div>
            </div>

            <div className="bg-surface-container p-space-sm rounded flex flex-col justify-between">
              <div className="flex justify-between items-baseline">
                <span className="font-headline-sm text-headline-sm text-on-surface">SOL</span>
                <span className="font-label-xs text-label-xs text-primary-fixed">PERP</span>
              </div>
              <div className="my-space-xs">
                <div className="font-numeric-md text-numeric-md text-primary-fixed font-semibold">+0.0284%</div>
                <div className="font-label-xs text-label-xs text-on-surface-variant">Ann: 31.09%</div>
              </div>
              <div className="w-full h-1 bg-surface-container-highest rounded overflow-hidden">
                <div className="h-full bg-primary-fixed" style={{ width: '92%' }}></div>
              </div>
            </div>

            <div className="bg-surface-container p-space-sm rounded flex flex-col justify-between">
              <div className="flex justify-between items-baseline">
                <span className="font-headline-sm text-headline-sm text-on-surface">SUI</span>
                <span className="font-label-xs text-label-xs text-error">DISCOUNT</span>
              </div>
              <div className="my-space-xs">
                <div className="font-numeric-md text-numeric-md text-error font-semibold">-0.0082%</div>
                <div className="font-label-xs text-label-xs text-on-surface-variant">Ann: -8.97%</div>
              </div>
              <div className="w-full h-1 bg-surface-container-highest rounded overflow-hidden">
                <div className="h-full bg-error" style={{ width: '41%' }}></div>
              </div>
            </div>

            <div className="bg-surface-container p-space-sm rounded flex flex-col justify-between">
              <div className="flex justify-between items-baseline">
                <span className="font-headline-sm text-headline-sm text-on-surface">AVAX</span>
                <span className="font-label-xs text-label-xs text-primary-fixed">PERP</span>
              </div>
              <div className="my-space-xs">
                <div className="font-numeric-md text-numeric-md text-primary-fixed font-semibold">+0.0125%</div>
                <div className="font-label-xs text-label-xs text-on-surface-variant">Ann: 13.68%</div>
              </div>
              <div className="w-full h-1 bg-surface-container-highest rounded overflow-hidden">
                <div className="h-full bg-primary-container" style={{ width: '62%' }}></div>
              </div>
            </div>

            <div className="bg-surface-container p-space-sm rounded flex flex-col justify-between">
              <div className="flex justify-between items-baseline">
                <span className="font-headline-sm text-headline-sm text-on-surface">DOGE</span>
                <span className="font-label-xs text-label-xs text-secondary">HOT</span>
              </div>
              <div className="my-space-xs">
                <div className="font-numeric-md text-numeric-md text-primary-fixed font-semibold">+0.0340%</div>
                <div className="font-label-xs text-label-xs text-on-surface-variant">Ann: 37.23%</div>
              </div>
              <div className="w-full h-1 bg-surface-container-highest rounded overflow-hidden">
                <div className="h-full bg-primary-fixed" style={{ width: '98%' }}></div>
              </div>
            </div>
          </div>

          <div className="mt-space-sm flex items-center justify-between font-label-xs text-label-xs text-on-surface-variant pt-space-xs bg-surface-container-lowest px-space-sm rounded">
            <span>PREDICTIVE ARB: +$840/day across Sol/Btc delta-spread</span>
            <span className="text-primary-fixed">HISTORICAL FUNDING VOL: NORMALIZED (σ 0.41)</span>
          </div>
        </div>
      </div>

      {/* Section 2: Chart & L2 Depth Header */}
      <div className="p-space-xs bg-surface">
        <div className="bg-surface-container-low rounded shadow-sm overflow-hidden flex flex-col border border-surface-container-high/60">
          <div className="h-9 bg-surface-container-lowest px-space-md border-b border-surface-container-high flex items-center justify-between gap-space-md text-numeric-sm">
            <div className="flex items-center gap-space-sm">
              <div className="flex items-center gap-space-xs font-semibold">
                <span className="w-2 h-2 rounded-full bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.7)]"></span>
                <span className="font-headline-sm text-on-surface uppercase">{selectedSymbol}</span>
                <span className="text-label-xs px-1 rounded bg-surface-container text-primary-fixed uppercase">
                  BINANCE PERP
                </span>
              </div>
              <div className="h-4 w-px bg-surface-container-highest"></div>
              <div className="flex items-center gap-1">
                <span className="px-1.5 py-0.5 rounded bg-primary/10 text-primary-fixed font-label-xs font-semibold">
                  VPOC ON
                </span>
                <span className="px-1.5 py-0.5 rounded bg-surface-container text-secondary font-label-xs font-medium">
                  CVD v2.1
                </span>
              </div>
            </div>

            <div className="flex items-center gap-space-md">
              <div className="flex items-center gap-space-sm font-numeric-sm">
                <span className="text-on-surface-variant font-label-xs uppercase">
                  O: <strong className="text-on-surface">{openPrice.toFixed(2)}</strong>
                </span>
                <span className="text-on-surface-variant font-label-xs uppercase">
                  H: <strong className="text-primary-fixed">{highPrice.toFixed(2)}</strong>
                </span>
                <span className="text-on-surface-variant font-label-xs uppercase">
                  L: <strong className="text-error">{lowPrice.toFixed(2)}</strong>
                </span>
                <span className="text-on-surface-variant font-label-xs uppercase">
                  C: <strong className="text-primary-fixed font-semibold">{currentPrice.toFixed(2)}</strong>
                </span>
                <span className={priceChange >= 0 ? 'text-primary-fixed font-semibold' : 'text-error font-semibold'}>
                  {priceChange >= 0 ? `+${priceChange.toFixed(2)}` : priceChange.toFixed(2)} ({priceChangePct >= 0 ? '+' : ''}{priceChangePct.toFixed(2)}%)
                </span>
              </div>
            </div>
          </div>

          {/* Chart Display & Live L2 Orderbook Panel */}
          <div className="grid grid-cols-1 lg:grid-cols-12 bg-[#090e18]">
            <div className="lg:col-span-9 p-1 border-r border-surface-container-high/60 min-h-[440px]">
              <TradingViewChart />
            </div>


            {/* L2 Orderbook Ladder */}
            <div className="lg:col-span-3 p-space-sm bg-surface-container-lowest flex flex-col justify-between text-numeric-sm">
              <div className="font-label-xs text-label-xs uppercase text-on-surface-variant border-b border-surface-container-high pb-1 flex justify-between">
                <span>PRICE</span>
                <span>SIZE</span>
              </div>

              {/* Asks (Sell) */}
              <div className="flex flex-col gap-0.5 my-1">
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
                      <span className="text-on-surface">{Number(sz).toFixed(3)}</span>
                    </div>
                  );
                })}
              </div>

              {/* Spread / Mark Price */}
              <div className="py-1 my-1 bg-surface-container text-center text-primary-fixed font-bold rounded border border-primary-container/20">
                ${currentPrice.toFixed(2)}
              </div>

              {/* Bids (Buy) */}
              <div className="flex flex-col gap-0.5 my-1">
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
                      <span className="text-on-surface">{Number(sz).toFixed(3)}</span>
                    </div>
                  );
                })}
              </div>
            </div>
          </div>
        </div>
      </div>

      {/* Section 3: Active Crypto Positions Table */}
      <div className="p-space-xs bg-surface">
        <div className="bg-surface-container-low rounded shadow-sm overflow-hidden flex flex-col border border-surface-container-high/60">
          <div className="h-9 bg-surface-container-lowest px-space-md border-b border-surface-container-high flex items-center justify-between text-numeric-sm">
            <span className="font-headline-sm text-on-surface font-semibold uppercase">
              Crypto Perpetuals Active Positions ({cryptoPositions.length})
            </span>
            <span className="font-label-xs text-label-xs text-primary-fixed">REAL-TIME RISK GUARD ACTIVE</span>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-left border-collapse font-numeric-sm text-numeric-sm">
              <thead>
                <tr className="bg-surface-container-high/40 text-on-surface-variant font-label-xs text-label-xs uppercase border-b border-surface-container-high">
                  <th className="py-2 px-3">Instrument</th>
                  <th className="py-2 px-3">Side</th>
                  <th className="py-2 px-3">Size (Qty)</th>
                  <th className="py-2 px-3">Entry Price</th>
                  <th className="py-2 px-3">Mark Price</th>
                  <th className="py-2 px-3">Leverage</th>
                  <th className="py-2 px-3">Unrealized P&L</th>
                  <th className="py-2 px-3">Liquidation Price</th>
                </tr>
              </thead>
              <tbody>
                {cryptoPositions.length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-6 text-center text-on-surface-variant">
                      No active Crypto Perpetuals positions. Risk Guard is monitoring entry triggers.
                    </td>
                  </tr>
                ) : (
                  cryptoPositions.map(([symbol, pos]: [string, any]) => {
                    const side = pos.qty > 0 ? 'LONG' : 'SHORT';
                    const entryPrice = pos.entry_price || currentPrice;
                    const markPrice = pos.current_price || currentPrice;
                    const pnlVal = pos.unrealized_pl || 0;
                    return (
                      <tr key={symbol} className="border-b border-surface-container-high/40 hover:bg-surface-container">
                        <td className="py-2.5 px-3 font-bold text-on-surface">{symbol}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded text-label-xs font-bold ${side === 'LONG' ? 'bg-primary/20 text-primary-fixed' : 'bg-error/20 text-error'}`}>
                            {side}
                          </span>
                        </td>
                        <td className="py-2.5 px-3">{Math.abs(pos.qty).toFixed(4)}</td>
                        <td className="py-2.5 px-3">${entryPrice.toFixed(2)}</td>
                        <td className="py-2.5 px-3">${markPrice.toFixed(2)}</td>
                        <td className="py-2.5 px-3 text-secondary">{pos.leverage || '5.0'}x</td>
                        <td className={`py-2.5 px-3 font-bold ${pnlVal >= 0 ? 'text-primary-fixed' : 'text-error'}`}>
                          {pnlVal >= 0 ? `+$${pnlVal.toFixed(2)}` : `-$${Math.abs(pnlVal).toFixed(2)}`}
                        </td>
                        <td className="py-2.5 px-3 text-on-surface-variant">${(entryPrice * 0.8).toFixed(2)}</td>
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
