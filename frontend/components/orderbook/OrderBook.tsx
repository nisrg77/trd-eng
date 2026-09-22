'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';

export const OrderBookComponent: React.FC = () => {
  const orderBook = useTradingStore((state) => state.orderBook);

  const maxBidTotal = orderBook.bids.reduce((acc, b) => Math.max(acc, b.total), 1);
  const maxAskTotal = orderBook.asks.reduce((acc, a) => Math.max(acc, a.total), 1);

  return (
    <div className="w-full h-full min-h-[440px] bg-[#090d16] border border-slate-800 rounded-xl p-3 flex flex-col font-mono text-xs select-none shadow-xl">
      <div className="flex items-center justify-between pb-2 border-b border-slate-800 mb-2">
        <span className="text-slate-300 font-bold uppercase tracking-wider">Depth / Order Book</span>
        <span className="text-slate-400">Spread: <strong className="text-slate-200">${orderBook.spread.toFixed(2)}</strong></span>
      </div>

      <div className="grid grid-cols-3 text-slate-500 pb-1 px-1 border-b border-slate-800/50">
        <span>Price</span>
        <span className="text-right">Size</span>
        <span className="text-right">Total</span>
      </div>

      {/* ASKS (Sells) */}
      <div className="flex flex-col-reverse flex-1 overflow-y-auto space-y-0.5 space-y-reverse py-1 max-h-[170px]">
        {orderBook.asks.slice(0, 8).map((ask, i) => {
          const depthPct = (ask.total / maxAskTotal) * 100;
          return (
            <div key={`ask-${i}`} className="relative grid grid-cols-3 px-1 py-0.5 text-rose-400 hover:bg-slate-800/40 rounded">
              <div
                className="absolute right-0 top-0 bottom-0 bg-rose-500/10 transition-all pointer-events-none rounded"
                style={{ width: `${depthPct}%` }}
              />
              <span className="z-10 font-semibold">${ask.price.toFixed(2)}</span>
              <span className="z-10 text-right text-slate-300">{ask.size.toFixed(4)}</span>
              <span className="z-10 text-right text-slate-500">{ask.total.toFixed(4)}</span>
            </div>
          );
        })}
      </div>

      {/* SPREAD INDICATOR */}
      <div className="my-2 py-1.5 bg-slate-900 border-y border-slate-800 text-center font-bold text-slate-200 rounded">
        Mid Price: ${orderBook.bids[0]?.price ? ((orderBook.bids[0].price + orderBook.asks[0]?.price) / 2).toFixed(2) : '86,150.00'}
      </div>

      {/* BIDS (Buys) */}
      <div className="flex flex-col flex-1 overflow-y-auto space-y-0.5 py-1 max-h-[170px]">
        {orderBook.bids.slice(0, 8).map((bid, i) => {
          const depthPct = (bid.total / maxBidTotal) * 100;
          return (
            <div key={`bid-${i}`} className="relative grid grid-cols-3 px-1 py-0.5 text-emerald-400 hover:bg-slate-800/40 rounded">
              <div
                className="absolute right-0 top-0 bottom-0 bg-emerald-500/10 transition-all pointer-events-none rounded"
                style={{ width: `${depthPct}%` }}
              />
              <span className="z-10 font-semibold">${bid.price.toFixed(2)}</span>
              <span className="z-10 text-right text-slate-300">{bid.size.toFixed(4)}</span>
              <span className="z-10 text-right text-slate-500">{bid.total.toFixed(4)}</span>
            </div>
          );
        })}
      </div>
    </div>
  );
};
