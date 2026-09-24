'use client';

import React, { useState } from 'react';
import { useTradingStore } from '@/store/useTradingStore';

export const TradeLogsTerminal: React.FC = () => {
  const { executions, quotaState, goalSummary } = useTradingStore();
  const [filterAsset, setFilterAsset] = useState<'ALL' | 'CRYPTO' | 'STOCKS'>('ALL');

  const filteredLogs = executions.filter((ex) => {
    const isCrypto = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BTCUSDT.P', 'ETHUSDT.P'].includes(ex.instrument);
    if (filterAsset === 'CRYPTO') return isCrypto;
    if (filterAsset === 'STOCKS') return !isCrypto;
    return true;
  });

  const cryptoCompleted = goalSummary?.crypto_completed ?? quotaState?.crypto?.completed ?? 0;
  const stockCompleted = goalSummary?.stock_completed ?? quotaState?.futures?.completed ?? 0;
  const totalCompleted = cryptoCompleted + stockCompleted;

  const cryptoWins = quotaState?.crypto?.wins ?? 0;
  const stockWins = quotaState?.futures?.wins ?? 0;
  const totalWins = cryptoWins + stockWins;
  const winRatePct = totalCompleted > 0 ? (totalWins / totalCompleted) * 100 : 0.0;

  return (
    <div className="flex flex-col w-full bg-surface min-h-screen">
      {/* Top Banner: Goal & Risk Gating Module Summary */}
      <div className="w-full bg-surface-container-lowest px-6 py-5 border-b border-surface-container-high/60 shadow-sm">
        <div className="flex items-center justify-between mb-4">
          <div className="flex items-center gap-3">
            <span className="w-2.5 h-2.5 rounded-full bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.7)]"></span>
            <span className="font-mono text-sm uppercase text-slate-100 font-bold">
              Goal & Risk Gating Module — Daily Quota & Circuit Breaker Telemetry
            </span>
          </div>
          <span className="font-mono text-[11px] uppercase px-2.5 py-1 bg-primary/10 text-primary-fixed border border-primary/20 rounded font-semibold">
            ATOMIC STATE PERSISTED (`quota_state.json`)
          </span>
        </div>

        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          {/* Crypto Ceiling Card */}
          <div className="bg-surface-container-low p-4 rounded-xl border border-surface-container-high shadow-md">
            <div className="flex justify-between items-center text-xs font-mono text-on-surface-variant uppercase">
              <span>Crypto Daily Ceiling</span>
              <span className="text-primary-fixed font-bold">{cryptoCompleted} / 20 TRADES</span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded-full overflow-hidden my-2.5">
              <div
                className="h-full bg-primary-container rounded-full"
                style={{ width: `${Math.min(100, (cryptoCompleted / 20) * 100)}%` }}
              ></div>
            </div>
            <div className="text-[11px] text-on-surface-variant font-mono">
              {20 - cryptoCompleted} daily trades remaining
            </div>
          </div>

          {/* US Equities Ceiling Card */}
          <div className="bg-surface-container-low p-4 rounded-xl border border-surface-container-high shadow-md">
            <div className="flex justify-between items-center text-xs font-mono text-on-surface-variant uppercase">
              <span>US Equities Daily Ceiling</span>
              <span className="text-primary-fixed font-bold">{stockCompleted} / 80 TRADES</span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded-full overflow-hidden my-2.5">
              <div
                className="h-full bg-primary-container rounded-full"
                style={{ width: `${Math.min(100, (stockCompleted / 80) * 100)}%` }}
              ></div>
            </div>
            <div className="text-[11px] text-on-surface-variant font-mono">
              {80 - stockCompleted} trades remaining before auto-throttle
            </div>
          </div>

          {/* Daily 4% Loss Circuit Breaker */}
          <div className="bg-surface-container-low p-4 rounded-xl border border-surface-container-high shadow-md">
            <div className="flex justify-between items-center text-xs font-mono text-on-surface-variant uppercase">
              <span>Daily Capital Depletion Stop</span>
              <span className={goalSummary?.engine_paused ? 'text-error font-bold' : 'text-primary-fixed font-bold'}>
                {goalSummary?.engine_paused ? 'STOPPED' : 'ACTIVE ($1,000 CAP)'}
              </span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded-full overflow-hidden my-2.5">
              <div
                className={`h-full rounded-full ${goalSummary?.engine_paused ? 'bg-error' : 'bg-primary-container'}`}
                style={{ width: `${Math.min(100, (Math.abs(goalSummary?.monthly_pnl_usd || 0.0) / 1000.0) * 100)}%` }}
              ></div>
            </div>
            <div className="text-[11px] text-on-surface-variant font-mono">
              System stops if $1,000 capital is completely finished
            </div>
          </div>

          {/* Current Session Win Rate */}
          <div className="bg-surface-container-low p-4 rounded-xl border border-surface-container-high shadow-md">
            <div className="flex justify-between items-center text-xs font-mono text-on-surface-variant uppercase">
              <span>Session Win Rate</span>
              <span className="text-primary-fixed font-bold">{totalCompleted > 0 ? `${winRatePct.toFixed(1)}%` : 'N/A (0 Trades)'}</span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded-full overflow-hidden my-2.5">
              <div
                className="h-full bg-primary-container rounded-full"
                style={{ width: `${totalCompleted > 0 ? winRatePct : 0}%` }}
              ></div>
            </div>
            <div className="text-[11px] text-on-surface-variant font-mono">
              Total Executed: <strong className="text-slate-200">{totalCompleted} trades</strong>
            </div>
          </div>
        </div>
      </div>

      {/* Section 2: Asset-Filtered Trade Audit Table with proper spacing */}
      <div className="p-6 space-y-6 flex-1 w-full">
        <div className="bg-surface-container-low rounded-xl shadow-lg overflow-hidden flex flex-col border border-surface-container-high/60">
          {/* Table Header & Asset Filter Tabs */}
          <div className="h-12 bg-surface-container-lowest px-5 border-b border-surface-container-high flex flex-wrap items-center justify-between gap-4 font-mono text-xs">
            <div className="flex items-center gap-4">
              <span className="font-bold text-slate-100 uppercase">
                Execution Audit & Order History ({filteredLogs.length})
              </span>
              <div className="flex items-center gap-1 bg-surface-container p-1 rounded-lg">
                <button
                  onClick={() => setFilterAsset('ALL')}
                  className={`px-3 py-1 rounded-md transition-all font-bold ${
                    filterAsset === 'ALL'
                      ? 'bg-surface-container-high text-primary shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  ALL TRADES
                </button>
                <button
                  onClick={() => setFilterAsset('CRYPTO')}
                  className={`px-3 py-1 rounded-md transition-all font-bold ${
                    filterAsset === 'CRYPTO'
                      ? 'bg-surface-container-high text-primary shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  CRYPTO PERPETUALS
                </button>
                <button
                  onClick={() => setFilterAsset('STOCKS')}
                  className={`px-3 py-1 rounded-md transition-all font-bold ${
                    filterAsset === 'STOCKS'
                      ? 'bg-surface-container-high text-primary shadow-sm'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  US STOCK FUTURES
                </button>
              </div>
            </div>

            <div className="text-[11px] text-on-surface-variant uppercase">
              STREAM: <strong className="text-primary-fixed">LIVE WEBSOCKET AUDIT LOG</strong>
            </div>
          </div>

          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left border-collapse font-mono text-xs">
              <thead>
                <tr className="bg-slate-900 text-slate-400 uppercase text-[11px] border-b border-slate-800">
                  <th className="py-3 px-4">Order ID</th>
                  <th className="py-3 px-4">Timestamp</th>
                  <th className="py-3 px-4">Asset Class</th>
                  <th className="py-3 px-4">Instrument</th>
                  <th className="py-3 px-4">Side</th>
                  <th className="py-3 px-4">Price</th>
                  <th className="py-3 px-4">Quantity</th>
                  <th className="py-3 px-4">Risk State</th>
                  <th className="py-3 px-4">Realized P&L</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-10 text-center text-slate-500 font-mono text-xs">
                      No executions logged matching selected filter. Submitting live orders...
                    </td>
                  </tr>
                ) : (
                  filteredLogs.map((log: any, idx: number) => {
                    const isCrypto = ['BTC-USD', 'ETH-USD', 'SOL-USD', 'BTCUSDT.P', 'ETHUSDT.P'].includes(log.instrument);
                    const assetClass = isCrypto ? 'CRYPTO' : 'US STOCKS';
                    const side = log.action || 'BUY';
                    const isApproved = log.risk_state === 'APPROVED';
                    const pnlVal = log.realized_pnl || 0.0;
                    const dateStr = log.timestamp_executed
                      ? new Date(log.timestamp_executed * 1000).toISOString().substring(11, 19)
                      : '14:28:09';

                    return (
                      <tr key={log.order_id || idx} className="border-b border-surface-container-high/40 hover:bg-surface-container transition-colors">
                        <td className="py-3 px-4 font-mono text-xs text-slate-400">
                          {log.order_id || `ord_${idx + 100}`}
                        </td>
                        <td className="py-3 px-4 text-on-surface-variant">{dateStr}</td>
                        <td className="py-3 px-4">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isCrypto ? 'bg-primary/10 text-primary-fixed border border-primary/20' : 'bg-secondary/10 text-secondary border border-secondary/20'}`}>
                            {assetClass}
                          </span>
                        </td>
                        <td className="py-3 px-4 font-bold text-slate-100">{log.instrument}</td>
                        <td className="py-3 px-4">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${side === 'BUY' ? 'bg-primary/20 text-primary-fixed border border-primary/30' : 'bg-error/20 text-error border border-error/30'}`}>
                            {side}
                          </span>
                        </td>
                        <td className="py-3 px-4">${(log.price || 100).toFixed(2)}</td>
                        <td className="py-3 px-4">{(log.quantity || 1.0).toFixed(4)}</td>
                        <td className="py-3 px-4">
                          <span className={`px-2 py-0.5 rounded text-[10px] font-bold ${isApproved ? 'bg-primary/20 text-primary-fixed border border-primary/30' : 'bg-error/20 text-error border border-error/30'}`}>
                            {isApproved ? 'APPROVED' : 'REJECTED'}
                          </span>
                        </td>
                        <td className={`py-3 px-4 font-bold ${pnlVal >= 0 ? 'text-primary-fixed' : 'text-error'}`}>
                          {pnlVal > 0 ? `+$${pnlVal.toFixed(2)}` : pnlVal < 0 ? `-$${Math.abs(pnlVal).toFixed(2)}` : '$0.00'}
                        </td>
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
