'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';

export const StitchSidebar: React.FC = () => {
  const { connectionStatus, latencyMs, account, goalSummary } = useTradingStore();

  const isConnected = connectionStatus === 'CONNECTED';
  const cryptoTrades = goalSummary?.crypto_trades_used ?? '0/20';
  const stockTrades = goalSummary?.stock_trades_used ?? '0/80';

  return (
    <aside className="fixed left-0 top-20 bottom-0 w-60 bg-slate-950/95 z-40 flex flex-col justify-between py-5 px-3 border-r border-slate-800/80 shadow-2xl backdrop-blur-md select-none">
      <div className="flex flex-col gap-5">
        {/* Sleeve Allocation Card */}
        <div className="bg-slate-900/80 p-3.5 rounded-xl border border-slate-800/80 flex flex-col gap-2.5">
          <div className="flex items-center justify-between">
            <span className="font-mono text-[11px] font-bold uppercase tracking-wider text-slate-400">
              Daily Sleeve Quota
            </span>
            <span className="px-1.5 py-0.5 rounded bg-cyan-500/10 text-cyan-400 font-mono text-[10px] font-bold border border-cyan-500/20">
              $1,000 CAP
            </span>
          </div>

          <div className="space-y-2 font-mono text-xs">
            <div>
              <div className="flex justify-between text-slate-300 pb-1">
                <span>Crypto Perpetuals (20%)</span>
                <span className="text-emerald-400 font-bold">{cryptoTrades}</span>
              </div>
              <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full bg-emerald-400 rounded-full" style={{ width: '20%' }}></div>
              </div>
            </div>

            <div>
              <div className="flex justify-between text-slate-300 pb-1">
                <span>US Stock Futures (80%)</span>
                <span className="text-cyan-400 font-bold">{stockTrades}</span>
              </div>
              <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
                <div className="h-full bg-cyan-400 rounded-full" style={{ width: '80%' }}></div>
              </div>
            </div>
          </div>
        </div>

        {/* Engine Gateways Status */}
        <div className="flex flex-col gap-2">
          <div className="px-2 font-mono text-[11px] font-bold uppercase text-slate-400 tracking-wider">
            Engine Gateways
          </div>
          <div className="bg-slate-900/60 p-3 rounded-xl border border-slate-800/70 flex flex-col gap-2 font-mono text-xs">
            <div className="flex justify-between items-center text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                Binance aggTrade
              </span>
              <span className="text-emerald-400 font-semibold text-[11px]">WEBSOCKET</span>
            </div>
            <div className="flex justify-between items-center text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                CME SSF Screener
              </span>
              <span className="text-cyan-400 font-semibold text-[11px]">ACTIVE</span>
            </div>
            <div className="flex justify-between items-center text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                Dedicated Chart Stream
              </span>
              <span className="text-emerald-400 font-semibold text-[11px]">ISOLATED</span>
            </div>
            <div className="flex justify-between items-center text-slate-300">
              <span className="flex items-center gap-1.5">
                <span className="w-1.5 h-1.5 rounded-full bg-emerald-400"></span>
                Simulated 10x OMS
              </span>
              <span className="text-slate-300 font-semibold text-[11px]">ARMED</span>
            </div>
          </div>
        </div>

        {/* Execution Guard & Limits */}
        <div className="flex flex-col gap-2">
          <div className="px-2 font-mono text-[11px] font-bold uppercase text-slate-400 tracking-wider">
            Hardened Risk Guard
          </div>
          <div className="bg-slate-900/60 p-3 rounded-xl border border-slate-800/70 flex flex-col gap-2 font-mono text-xs">
            <div className="flex justify-between items-center">
              <span className="text-slate-400">Risk Budget / Trade:</span>
              <span className="text-emerald-400 font-bold">$10.00 USD</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-slate-400">Daily Loss Hard Stop:</span>
              <span className="text-slate-200 font-semibold">-4.0% NAV</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-slate-400">Max Monthly DD:</span>
              <span className="text-slate-200 font-semibold">-18.0% NAV</span>
            </div>
            <div className="flex justify-between items-center">
              <span className="text-slate-400">Dead-Day Filter:</span>
              <span className="text-cyan-400 font-semibold">P10 Active</span>
            </div>
          </div>
        </div>
      </div>

      {/* Footer System Telemetry */}
      <div className="p-3.5 bg-slate-900/90 rounded-xl border border-slate-800/80 flex flex-col gap-2 font-mono">
        <div className="flex justify-between items-center text-xs">
          <span className="text-slate-400 uppercase text-[11px]">Engine Health</span>
          <span className={`font-bold text-[11px] ${isConnected ? 'text-emerald-400' : 'text-rose-400'}`}>
            {isConnected ? 'ONLINE' : 'OFFLINE'}
          </span>
        </div>
        <div className="w-full h-1.5 bg-slate-800 rounded-full overflow-hidden">
          <div
            className={`h-full rounded-full ${isConnected ? 'bg-emerald-400' : 'bg-rose-500'}`}
            style={{ width: isConnected ? '100%' : '15%' }}
          ></div>
        </div>
        <div className="flex justify-between items-center text-[10px] text-slate-400 pt-0.5">
          <span>WS Latency: {latencyMs}ms</span>
          <span>Memory: RAM Zero-Tick</span>
        </div>
      </div>
    </aside>
  );
};
