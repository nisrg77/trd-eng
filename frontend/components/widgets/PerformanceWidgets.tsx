'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { formatCurrency } from '@/lib/utils';
import { TrendingUp, ShieldAlert, Cpu, Activity } from 'lucide-react';

export const PerformanceWidgets: React.FC = () => {
  const account = useTradingStore((state) => state.account);
  const latencyMs = useTradingStore((state) => state.latencyMs);
  const engineStatus = useTradingStore((state) => state.engineStatus);
  const executions = useTradingStore((state) => state.executions);

  const totalFilled = executions.filter((e) => e.oms_state === 'FILLED').length;
  const winCount = executions.filter((e) => e.oms_state === 'FILLED' && (e.notional_value || 0) > 0).length;
  const winRatePct = totalFilled > 0 ? ((winCount / totalFilled) * 100).toFixed(1) : '0.0';

  const pnlIsPositive = (account.realized_pl || 0) >= 0;

  return (
    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-6 gap-3">
      {/* Total Equity & Realized PnL */}
      <div className="bg-[#090d16] border border-slate-800 rounded-xl p-3.5 flex items-center justify-between shadow-lg">
        <div>
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Account Equity</span>
          <div className="text-xl font-bold text-slate-100 font-mono mt-0.5">
            {formatCurrency(account.equity || 1000)}
          </div>
          <div className={`text-xs font-mono font-semibold mt-1 ${pnlIsPositive ? 'text-emerald-400' : 'text-rose-400'}`}>
            Realized PnL: {pnlIsPositive ? '+' : ''}{formatCurrency(account.realized_pl || 0)}
          </div>
        </div>
        <div className="h-10 w-10 rounded-lg bg-emerald-500/10 border border-emerald-500/20 flex items-center justify-center text-emerald-400">
          <TrendingUp className="h-5 w-5" />
        </div>
      </div>

      {/* Win/Loss Ratio */}
      <div className="bg-[#090d16] border border-slate-800 rounded-xl p-3.5 flex items-center justify-between shadow-lg">
        <div>
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Win/Loss Ratio</span>
          <div className="text-xl font-bold text-slate-100 font-mono mt-0.5">
            {winRatePct}%
          </div>
          <div className="text-xs text-slate-400 font-mono mt-1">
            Total Trades: {executions.length}
          </div>
        </div>
        <div className="h-10 w-10 rounded-lg bg-blue-500/10 border border-blue-500/20 flex items-center justify-center text-blue-400">
          <Activity className="h-5 w-5" />
        </div>
      </div>

      {/* Active Drawdown */}
      <div className="bg-[#090d16] border border-slate-800 rounded-xl p-3.5 flex items-center justify-between shadow-lg">
        <div>
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Active Drawdown</span>
          <div className="text-xl font-bold text-rose-400 font-mono mt-0.5">
            -{(account.active_drawdown_pct || 0.0).toFixed(2)}%
          </div>
          <div className="text-xs text-slate-400 font-mono mt-1">
            Max Limit: 15.0%
          </div>
        </div>
        <div className="h-10 w-10 rounded-lg bg-rose-500/10 border border-rose-500/20 flex items-center justify-center text-rose-400">
          <ShieldAlert className="h-5 w-5" />
        </div>
      </div>

      {/* Engine Status & Latency */}
      <div className="bg-[#090d16] border border-slate-800 rounded-xl p-3.5 flex items-center justify-between shadow-lg">
        <div>
          <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Engine Telemetry</span>
          <div className="text-xl font-bold text-emerald-400 font-mono mt-0.5 flex items-center gap-2">
            <span>{engineStatus}</span>
          </div>
          <div className="text-xs text-slate-400 font-mono mt-1">
            Latency: <strong className="text-cyan-400">{latencyMs}ms</strong>
          </div>
        </div>
        <div className="h-10 w-10 rounded-lg bg-cyan-500/10 border border-cyan-500/20 flex items-center justify-center text-cyan-400">
          <Cpu className="h-5 w-5" />
        </div>
      </div>

      {/* Quota Tracker */}
      <div className="bg-[#090d16] border border-slate-800 rounded-xl p-3.5 flex flex-col justify-center shadow-lg">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">Trade Quota Manager</span>
        <div className="flex justify-between mt-2">
          <div className="text-xs font-mono">
            Crypto: <span className="text-emerald-400">{useTradingStore((state) => state.quotaState.crypto?.completed || 0)}</span>/20
          </div>
          <div className="text-xs font-mono">
            US Fut: <span className="text-blue-400">{useTradingStore((state) => state.quotaState.futures?.completed || 0)}</span>/80
          </div>
        </div>
        <div className="w-full bg-slate-800 rounded-full h-1.5 mt-2">
          <div className="bg-gradient-to-r from-emerald-500 to-blue-500 h-1.5 rounded-full" style={{ width: `${((useTradingStore((state) => state.quotaState.crypto?.completed || 0) + (useTradingStore((state) => state.quotaState.futures?.completed || 0))) / 100) * 100}%` }}></div>
        </div>
      </div>

      {/* Screener Targets */}
      <div className="bg-[#090d16] border border-slate-800 rounded-xl p-3.5 flex flex-col justify-center shadow-lg">
        <span className="text-xs font-semibold text-slate-400 uppercase tracking-wider">US Stock Screener</span>
        <div className="flex justify-between items-center mt-2">
          <div className="flex flex-col">
            <span className="text-[10px] text-slate-500 font-mono mb-0.5">#1 LONG</span>
            <span className="text-sm font-bold text-emerald-400 font-mono bg-emerald-500/10 px-2 py-0.5 rounded border border-emerald-500/20">{useTradingStore((state) => state.screenerTargets.long || 'PENDING')}</span>
          </div>
          <div className="flex flex-col text-right">
            <span className="text-[10px] text-slate-500 font-mono mb-0.5">#55 SHORT</span>
            <span className="text-sm font-bold text-rose-400 font-mono bg-rose-500/10 px-2 py-0.5 rounded border border-rose-500/20">{useTradingStore((state) => state.screenerTargets.short || 'PENDING')}</span>
          </div>
        </div>
      </div>

    </div>
  );
};
