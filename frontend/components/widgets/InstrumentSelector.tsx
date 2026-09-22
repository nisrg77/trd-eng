'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { Instrument } from '@/types/trading';

const SYMBOLS: Instrument[] = ['BTC-USD', 'ETH-USD', 'AAPL', 'SPY'];

export const InstrumentSelector: React.FC = () => {
  const selectedSymbol = useTradingStore((state) => state.selectedSymbol);
  const setSelectedSymbol = useTradingStore((state) => state.setSelectedSymbol);
  const connectionStatus = useTradingStore((state) => state.connectionStatus);

  return (
    <div className="flex items-center space-x-3">
      <div className="flex items-center bg-[#090d16] border border-slate-800 rounded-lg p-1">
        {SYMBOLS.map((sym) => (
          <button
            key={sym}
            onClick={() => setSelectedSymbol(sym)}
            className={`px-3 py-1.5 text-xs font-semibold font-mono rounded-md transition-all ${
              selectedSymbol === sym
                ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-md'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            {sym}
          </button>
        ))}
      </div>

      <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-[#090d16] border border-slate-800 text-xs font-mono">
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            connectionStatus === 'CONNECTED'
              ? 'bg-emerald-400 animate-pulse'
              : connectionStatus === 'RECONNECTING'
              ? 'bg-amber-400 animate-ping'
              : 'bg-rose-500'
          }`}
        />
        <span className="text-slate-300 font-semibold">{connectionStatus}</span>
      </div>
    </div>
  );
};
