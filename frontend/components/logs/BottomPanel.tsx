'use client';

import React, { useState } from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { formatISTTime, formatCurrency } from '@/lib/utils';
import { Layers, History, BrainCircuit, Terminal } from 'lucide-react';

export const BottomPanel: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'positions' | 'executions' | 'signals' | 'logs'>('positions');

  const account = useTradingStore((state) => state.account);
  const executions = useTradingStore((state) => state.executions);
  const signals = useTradingStore((state) => state.signals);
  const logs = useTradingStore((state) => state.logs);

  const positionsList = Object.entries(account.positions || {}).map(([symbol, pos]) => ({
    symbol,
    ...pos,
  }));

  return (
    <div className="w-full bg-[#090d16] border border-slate-800 rounded-xl p-3 flex flex-col font-sans shadow-xl">
      {/* Tab Navigation Header */}
      <div className="flex items-center justify-between border-b border-slate-800 pb-2 mb-3">
        <div className="flex items-center space-x-2">
          <button
            onClick={() => setActiveTab('positions')}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'positions'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
            }`}
          >
            <Layers className="h-3.5 w-3.5" />
            <span>Open Positions ({positionsList.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('executions')}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'executions'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
            }`}
          >
            <History className="h-3.5 w-3.5" />
            <span>Trade History ({executions.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('signals')}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'signals'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
            }`}
          >
            <BrainCircuit className="h-3.5 w-3.5" />
            <span>ML Signals ({signals.length})</span>
          </button>

          <button
            onClick={() => setActiveTab('logs')}
            className={`flex items-center space-x-2 px-3 py-1.5 rounded-lg text-xs font-semibold transition-all ${
              activeTab === 'logs'
                ? 'bg-cyan-500/20 text-cyan-400 border border-cyan-500/30'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/40'
            }`}
          >
            <Terminal className="h-3.5 w-3.5" />
            <span>Engine Logs ({logs.length})</span>
          </button>
        </div>

        <span className="text-xs font-mono text-slate-500">
          Timezone: IST (UTC+5:30)
        </span>
      </div>

      {/* Tab Contents */}
      <div className="overflow-x-auto min-h-[180px] max-h-[260px] overflow-y-auto">
        {/* 1. POSITIONS */}
        {activeTab === 'positions' && (
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-slate-800/60 text-slate-400">
                <th className="pb-2">Instrument</th>
                <th className="pb-2">Quantity</th>
                <th className="pb-2">Entry Price</th>
                <th className="pb-2">Current Price</th>
                <th className="pb-2">Unrealized PnL ($)</th>
                <th className="pb-2">PnL (%)</th>
              </tr>
            </thead>
            <tbody>
              {positionsList.length === 0 ? (
                <tr>
                  <td colSpan={6} className="text-center py-6 text-slate-500">
                    No active positions currently open.
                  </td>
                </tr>
              ) : (
                positionsList.map((pos) => {
                  const isProfitable = pos.unrealized_pl >= 0;
                  return (
                    <tr key={pos.symbol} className="border-b border-slate-800/40 hover:bg-slate-800/30">
                      <td className="py-2 font-bold text-slate-100">{pos.symbol}</td>
                      <td className={`py-2 ${pos.qty >= 0 ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {pos.qty >= 0 ? 'LONG' : 'SHORT'} {Math.abs(pos.qty).toFixed(4)}
                      </td>
                      <td className="py-2 text-slate-300">${pos.entry_price?.toFixed(2)}</td>
                      <td className="py-2 text-slate-200">${pos.current_price?.toFixed(2)}</td>
                      <td className={`py-2 font-bold ${isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {isProfitable ? '+' : ''}${pos.unrealized_pl?.toFixed(2)}
                      </td>
                      <td className={`py-2 font-bold ${isProfitable ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {isProfitable ? '+' : ''}{((pos.unrealized_plpc || 0) * 100).toFixed(2)}%
                      </td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}

        {/* 2. EXECUTIONS */}
        {activeTab === 'executions' && (
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-slate-800/60 text-slate-400">
                <th className="pb-2">Time (IST)</th>
                <th className="pb-2">Order ID</th>
                <th className="pb-2">Instrument</th>
                <th className="pb-2">Side</th>
                <th className="pb-2">Alloc (%)</th>
                <th className="pb-2">Risk State</th>
                <th className="pb-2">OMS Status</th>
              </tr>
            </thead>
            <tbody>
              {executions.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-6 text-slate-500">
                    No execution logs available.
                  </td>
                </tr>
              ) : (
                executions.map((ex) => (
                  <tr key={ex.order_id} className="border-b border-slate-800/40 hover:bg-slate-800/30">
                    <td className="py-2 text-slate-400">{formatISTTime(ex.timestamp_proposed)}</td>
                    <td className="py-2 text-slate-300">{ex.order_id}</td>
                    <td className="py-2 font-bold text-slate-100">{ex.instrument}</td>
                    <td className={`py-2 font-bold ${ex.action === 'BUY' ? 'text-emerald-400' : 'text-rose-400'}`}>
                      {ex.action}
                    </td>
                    <td className="py-2 text-slate-300">{((ex.portfolio_allocation_pct || 0) * 100).toFixed(1)}%</td>
                    <td className="py-2">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          ex.risk_state === 'APPROVED'
                            ? 'bg-emerald-500/10 text-emerald-400 border border-emerald-500/20'
                            : 'bg-rose-500/10 text-rose-400 border border-rose-500/20'
                        }`}
                      >
                        {ex.risk_state}
                      </span>
                    </td>
                    <td className="py-2">
                      <span
                        className={`px-2 py-0.5 rounded text-[10px] font-bold ${
                          ex.oms_state === 'FILLED' || ex.oms_state === 'SUBMITTED'
                            ? 'bg-blue-500/10 text-blue-400 border border-blue-500/20'
                            : 'bg-amber-500/10 text-amber-400 border border-amber-500/20'
                        }`}
                      >
                        {ex.oms_state} {ex.oms_detail ? `(${ex.oms_detail})` : ''}
                      </span>
                    </td>
                  </tr>
                ))
              )}
            </tbody>
          </table>
        )}

        {/* 3. ML SIGNALS */}
        {activeTab === 'signals' && (
          <table className="w-full text-left font-mono text-xs">
            <thead>
              <tr className="border-b border-slate-800/60 text-slate-400">
                <th className="pb-2">Time (IST)</th>
                <th className="pb-2">Instrument</th>
                <th className="pb-2">Direction</th>
                <th className="pb-2">Confidence</th>
                <th className="pb-2">Regime</th>
                <th className="pb-2">Ridge / XGB / LSTM</th>
                <th className="pb-2">Latency</th>
              </tr>
            </thead>
            <tbody>
              {signals.length === 0 ? (
                <tr>
                  <td colSpan={7} className="text-center py-6 text-slate-500">
                    Waiting for live ML signals...
                  </td>
                </tr>
              ) : (
                signals.map((sig) => {
                  const isBullish = sig.direction_magnitude >= 0;
                  return (
                    <tr key={sig.signal_id} className="border-b border-slate-800/40 hover:bg-slate-800/30">
                      <td className="py-2 text-slate-400">{formatISTTime(sig.timestamp_generated)}</td>
                      <td className="py-2 font-bold text-slate-100">{sig.instrument}</td>
                      <td className={`py-2 font-bold ${isBullish ? 'text-emerald-400' : 'text-rose-400'}`}>
                        {isBullish ? 'BULLISH' : 'BEARISH'} ({(sig.direction_magnitude || 0).toFixed(3)})
                      </td>
                      <td className="py-2 text-cyan-400 font-bold">
                        {((sig.confidence_score || 0) * 100).toFixed(1)}%
                      </td>
                      <td className="py-2 text-slate-300 uppercase">{sig.regime_flag}</td>
                      <td className="py-2 text-slate-400">
                        {sig.per_model?.ridge?.toFixed(2)} | {sig.per_model?.xgb?.toFixed(2)} | {sig.per_model?.lstm?.toFixed(2)}
                      </td>
                      <td className="py-2 text-slate-400">{sig.latency_ms?.toFixed(1)}ms</td>
                    </tr>
                  );
                })
              )}
            </tbody>
          </table>
        )}

        {/* 4. SYSTEM LOGS */}
        {activeTab === 'logs' && (
          <div className="space-y-1 font-mono text-xs">
            {logs.map((log) => (
              <div key={log.id} className="flex items-center space-x-3 py-1 border-b border-slate-800/30">
                <span className="text-slate-500">{formatISTTime(log.timestamp)}</span>
                <span
                  className={`px-1.5 py-0.5 rounded text-[10px] font-bold ${
                    log.level === 'SUCCESS'
                      ? 'bg-emerald-500/10 text-emerald-400'
                      : log.level === 'WARN'
                      ? 'bg-amber-500/10 text-amber-400'
                      : log.level === 'ERROR'
                      ? 'bg-rose-500/10 text-rose-400'
                      : 'bg-blue-500/10 text-blue-400'
                  }`}
                >
                  [{log.source}] {log.level}
                </span>
                <span className="text-slate-200">{log.message}</span>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};
