'use client';

import React, { useMemo } from 'react';
import { useTradingStore } from '@/store/useTradingStore';

interface RecentTradesSectionProps {
  market: 'us' | 'crypto';
}

function isCrypto(instrument: string) {
  return /BTC|ETH|SOL|BNB|XRP|DOGE/i.test(instrument);
}

function money(n: number, d = 2) {
  const abs = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
  return (n < 0 ? '-' : '') + '$' + abs;
}

function fmtDate(ts: number): string {
  return new Date(ts * 1000).toLocaleDateString(undefined, {
    month: 'short', day: 'numeric', hour: '2-digit', minute: '2-digit',
  });
}

export const RecentTradesSection: React.FC<RecentTradesSectionProps> = ({ market }) => {
  const executions = useTradingStore((s) => s.executions);

  const filtered = useMemo(() => {
    return executions.filter((ex) =>
      market === 'crypto' ? isCrypto(ex.instrument) : !isCrypto(ex.instrument)
    ).slice(0, 20); // show latest 20
  }, [executions, market]);

  const badgeCls  = market === 'us' ? 'blue' : 'cyan';

  return (
    <div
      className="rounded-xl p-4 mt-3"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      <h2 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
        Recent trades
        <span className={`badge ${badgeCls}`}>{market === 'us' ? 'US · RTH' : 'Crypto · 24/7'}</span>
        <span className="subtle" style={{ marginLeft: 'auto', fontSize: 11 }}>
          {filtered.length} record{filtered.length !== 1 ? 's' : ''}
        </span>
      </h2>

      <div style={{ overflowX: 'auto' }}>
        <table style={{ minWidth: 700 }}>
          <thead>
            <tr>
              <th>Time</th>
              <th>Instrument</th>
              <th>Action</th>
              <th>Type</th>
              <th>Alloc %</th>
              <th>Risk state</th>
              <th>OMS</th>
              <th>Realized P/L</th>
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={8} style={{ textAlign: 'center', padding: '18px 0', color: 'var(--tx3)' }}>
                  No {market === 'us' ? 'US' : 'Crypto'} trades executed yet.
                </td>
              </tr>
            ) : (
              filtered.map((ex) => {
                const isBuy    = ex.action === 'BUY';
                const approved = ex.risk_state === 'APPROVED';
                const pnl      = ex.notional_value ?? 0;

                return (
                  <tr key={ex.order_id}>
                    <td>{fmtDate(ex.timestamp_proposed)}</td>
                    <td><b>{ex.instrument}</b></td>
                    <td><span className={`pill ${isBuy ? 'long' : 'short'}`}>{ex.action}</span></td>
                    <td>{ex.order_type}</td>
                    <td>{((ex.portfolio_allocation_pct ?? 0) * 100).toFixed(1)}%</td>
                    <td>
                      <span
                        className={`pill ${approved ? 'approved' : 'rejected'}`}
                        title={ex.failed_check ?? ''}
                      >
                        {ex.risk_state}
                      </span>
                    </td>
                    <td style={{ fontSize: 11, color: 'var(--tx2)' }}>
                      {ex.oms_state}{ex.oms_detail ? ` · ${ex.oms_detail}` : ''}
                    </td>
                    <td className={pnl >= 0 ? 'pos' : 'neg'}>
                      {pnl ? money(pnl) : '—'}
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
    </div>
  );
};
