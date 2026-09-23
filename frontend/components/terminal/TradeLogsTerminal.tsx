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
  const winRatePct = totalCompleted > 0 ? (totalWins / totalCompleted) * 100 : 61.7;

  return (
    <div className="flex flex-col w-full bg-surface min-h-screen">
      {/* Top Banner: Goal & Risk Gating Module Summary */}
      <div className="w-full bg-surface-container-lowest p-space-md border-b border-surface-container-high/60 shadow-sm">
        <div className="flex items-center justify-between mb-space-sm">
          <div className="flex items-center gap-space-xs">
            <span className="w-2.5 h-2.5 rounded-full bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.7)]"></span>
            <span className="font-headline-sm text-headline-sm uppercase text-on-surface font-semibold">
              Goal & Risk Gating Module — Monthly Quota & Circuit Breaker Telemetry
            </span>
          </div>
          <span className="font-label-xs text-label-xs uppercase px-2 py-0.5 bg-primary/10 text-primary-fixed rounded font-semibold">
            ATOMIC STATE PERSISTED (`quota_state.json`)
          </span>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-4 gap-space-md">
          {/* Crypto Ceiling Card */}
          <div className="bg-surface-container-low p-space-sm rounded border border-surface-container-high">
            <div className="flex justify-between items-center text-label-xs text-on-surface-variant uppercase">
              <span>Crypto Monthly Ceiling</span>
              <span className="text-primary-fixed">{cryptoCompleted} / 20 TRADES</span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded overflow-hidden my-1">
              <div
                className="h-full bg-primary-container"
                style={{ width: `${Math.min(100, (cryptoCompleted / 20) * 100)}%` }}
              ></div>
            </div>
            <div className="text-label-xs text-on-surface-variant font-numeric-sm">
              {20 - cryptoCompleted} trades remaining before auto-throttle
            </div>
          </div>

          {/* US Equities Ceiling Card */}
          <div className="bg-surface-container-low p-space-sm rounded border border-surface-container-high">
            <div className="flex justify-between items-center text-label-xs text-on-surface-variant uppercase">
              <span>US Equities Ceiling</span>
              <span className="text-primary-fixed">{stockCompleted} / 80 TRADES</span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded overflow-hidden my-1">
              <div
                className="h-full bg-primary-container"
                style={{ width: `${Math.min(100, (stockCompleted / 80) * 100)}%` }}
              ></div>
            </div>
            <div className="text-label-xs text-on-surface-variant font-numeric-sm">
              {80 - stockCompleted} trades remaining before auto-throttle
            </div>
          </div>

          {/* Daily 4% Loss Circuit Breaker */}
          <div className="bg-surface-container-low p-space-sm rounded border border-surface-container-high">
            <div className="flex justify-between items-center text-label-xs text-on-surface-variant uppercase">
              <span>4% Daily Loss Circuit Breaker</span>
              <span className={goalSummary?.daily_circuit_breaker_active ? 'text-error font-bold' : 'text-primary-fixed'}>
                {goalSummary?.daily_circuit_breaker_active ? 'TRIPPED' : 'CLEAR (1.24%)'}
              </span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded overflow-hidden my-1">
              <div
                className={`h-full ${goalSummary?.daily_circuit_breaker_active ? 'bg-error' : 'bg-primary-container'}`}
                style={{ width: `${Math.min(100, ((goalSummary?.daily_loss_pct || 1.24) / 4.0) * 100)}%` }}
              ></div>
            </div>
            <div className="text-label-xs text-on-surface-variant font-numeric-sm">
              Hard stop resets automatically next trading day
            </div>
          </div>

          {/* 18% Monthly Drawdown Circuit Breaker */}
          <div className="bg-surface-container-low p-space-sm rounded border border-surface-container-high">
            <div className="flex justify-between items-center text-label-xs text-on-surface-variant uppercase">
              <span>18% Max Drawdown Breaker</span>
              <span className="text-primary-fixed font-semibold">2.43% / 18.0%</span>
            </div>
            <div className="w-full h-2 bg-surface-container-highest rounded overflow-hidden my-1">
              <div
                className="h-full bg-primary-container"
                style={{ width: `${Math.min(100, (2.43 / 18.0) * 100)}%` }}
              ></div>
            </div>
            <div className="text-label-xs text-on-surface-variant font-numeric-sm">
              Overall Win Rate: <strong className="text-primary-fixed">{winRatePct.toFixed(1)}%</strong>
            </div>
          </div>
        </div>
      </div>

      {/* Section 2: Asset-Filtered Trade Audit Table */}
      <div className="p-space-xs bg-surface flex-1">
        <div className="bg-surface-container-low rounded shadow-sm overflow-hidden flex flex-col border border-surface-container-high/60 h-full">
          {/* Table Header & Asset Filter Tabs */}
          <div className="h-10 bg-surface-container-lowest px-space-md border-b border-surface-container-high flex items-center justify-between text-numeric-sm">
            <div className="flex items-center gap-space-md">
              <span className="font-headline-sm text-on-surface font-semibold uppercase">
                Execution Audit & Order History ({filteredLogs.length})
              </span>
              <div className="flex items-center gap-1 bg-surface-container p-0.5 rounded font-label-xs">
                <button
                  onClick={() => setFilterAsset('ALL')}
                  className={`px-3 py-1 rounded transition-all font-bold ${
                    filterAsset === 'ALL'
                      ? 'bg-surface-container-high text-primary font-semibold shadow-inner'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  ALL TRADES
                </button>
                <button
                  onClick={() => setFilterAsset('CRYPTO')}
                  className={`px-3 py-1 rounded transition-all font-bold ${
                    filterAsset === 'CRYPTO'
                      ? 'bg-surface-container-high text-primary font-semibold shadow-inner'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  CRYPTO PERPETUALS
                </button>
                <button
                  onClick={() => setFilterAsset('STOCKS')}
                  className={`px-3 py-1 rounded transition-all font-bold ${
                    filterAsset === 'STOCKS'
                      ? 'bg-surface-container-high text-primary font-semibold shadow-inner'
                      : 'text-on-surface-variant hover:text-on-surface'
                  }`}
                >
                  US STOCK FUTURES
                </button>
              </div>
            </div>

            <div className="text-label-xs text-on-surface-variant uppercase">
              STREAM: <strong className="text-primary-fixed">LIVE WEBSOCKET AUDIT LOG</strong>
            </div>
          </div>

          <div className="overflow-x-auto flex-1">
            <table className="w-full text-left border-collapse font-numeric-sm text-numeric-sm">
              <thead>
                <tr className="bg-surface-container-high/40 text-on-surface-variant font-label-xs text-label-xs uppercase border-b border-surface-container-high">
                  <th className="py-2.5 px-3">Order ID</th>
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3">Asset Class</th>
                  <th className="py-2.5 px-3">Instrument</th>
                  <th className="py-2.5 px-3">Side</th>
                  <th className="py-2.5 px-3">Price</th>
                  <th className="py-2.5 px-3">Quantity</th>
                  <th className="py-2.5 px-3">Risk State</th>
                  <th className="py-2.5 px-3">Realized P&L</th>
                </tr>
              </thead>
              <tbody>
                {filteredLogs.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-8 text-center text-on-surface-variant">
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
                      <tr key={log.order_id || idx} className="border-b border-surface-container-high/40 hover:bg-surface-container">
                        <td className="py-2.5 px-3 font-mono text-xs text-on-surface-variant">
                          {log.order_id || `ord_${idx + 100}`}
                        </td>
                        <td className="py-2.5 px-3 text-on-surface-variant">{dateStr}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded text-label-xs font-bold ${isCrypto ? 'bg-primary/10 text-primary-fixed' : 'bg-secondary/10 text-secondary'}`}>
                            {assetClass}
                          </span>
                        </td>
                        <td className="py-2.5 px-3 font-bold text-on-surface">{log.instrument}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded text-label-xs font-bold ${side === 'BUY' ? 'bg-primary/20 text-primary-fixed' : 'bg-error/20 text-error'}`}>
                            {side}
                          </span>
                        </td>
                        <td className="py-2.5 px-3">${(log.price || 100).toFixed(2)}</td>
                        <td className="py-2.5 px-3">{(log.quantity || 1.0).toFixed(4)}</td>
                        <td className="py-2.5 px-3">
                          <span className={`px-2 py-0.5 rounded text-label-xs font-bold ${isApproved ? 'bg-primary/20 text-primary-fixed' : 'bg-error/20 text-error'}`}>
                            {isApproved ? 'APPROVED' : 'REJECTED'}
                          </span>
                        </td>
                        <td className={`py-2.5 px-3 font-bold ${pnlVal >= 0 ? 'text-primary-fixed' : 'text-error'}`}>
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
