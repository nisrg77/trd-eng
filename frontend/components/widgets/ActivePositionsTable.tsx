'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';

interface ActivePositionsTableProps {
  market: 'us' | 'crypto';
}

function money(n: number, d = 2) {
  const abs = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: d,
    maximumFractionDigits: d,
  });
  return (n < 0 ? '-' : '') + '$' + abs;
}

export const ActivePositionsTable: React.FC<ActivePositionsTableProps> = ({ market }) => {
  const account = useTradingStore((s) => s.account);

  const allPositions = Object.entries(account.positions ?? {}).map(([symbol, pos]) => ({
    symbol,
    ...pos,
  }));

  const positions = allPositions.filter((p) =>
    market === 'crypto'
      ? /BTC|ETH|SOL|BNB|XRP|DOGE/i.test(p.symbol)
      : !/BTC|ETH|SOL|BNB|XRP|DOGE/i.test(p.symbol)
  );

  const badgeCls  = market === 'us' ? 'blue' : 'cyan';
  const badgeText = market === 'us' ? 'US · RTH' : 'Crypto · 24/7';

  return (
    <div
      className="rounded-xl p-4 mb-3"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      <h2 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px', display: 'flex', alignItems: 'center', gap: 8 }}>
        Active positions&nbsp;
        <span className={`badge ${badgeCls}`}>{badgeText}</span>
      </h2>

      <div className="tbl-wrap" style={{ overflowX: 'auto' }}>
        <table style={{ minWidth: 760 }}>
          <thead>
            <tr>
              <th>Symbol</th>
              <th>Side</th>
              <th>Qty</th>
              <th>Entry</th>
              <th>Current</th>
              <th>Unrl P/L</th>
              <th>P/L %</th>
              <th>Stop</th>
              <th>TP1</th>
              <th>TP2</th>
            </tr>
          </thead>
          <tbody>
            {positions.length === 0 ? (
              <tr>
                <td colSpan={10} style={{ textAlign: 'center', padding: '18px 0', color: 'var(--tx3)' }}>
                  No active {market === 'us' ? 'US' : 'Crypto'} positions.
                </td>
              </tr>
            ) : (
              positions.map((pos) => {
                const isLong   = (pos.qty ?? 0) >= 0;
                const pnlPos   = (pos.unrealized_pl ?? 0) >= 0;
                const plPct    = (pos.unrealized_plpc ?? 0) * 100;
                const entry    = pos.entry_price   ?? 0;
                const current  = pos.current_price ?? 0;
                const stop     = isLong ? entry * 0.985  : entry * 1.015;
                const tp1      = isLong ? entry * 1.012  : entry * 0.988;
                const tp2      = isLong ? entry * 1.024  : entry * 0.976;
                const qtyVal   = Math.abs(pos.qty ?? pos.size ?? 0);
                const qtyStr   = qtyVal < 0.01 ? qtyVal.toFixed(6) : qtyVal.toFixed(4);

                return (
                  <tr key={pos.symbol}>
                    <td><b>{pos.symbol}</b></td>
                    <td><span className={`pill ${isLong ? 'long' : 'short'}`}>{isLong ? 'LONG' : 'SHORT'}</span></td>
                    <td>{qtyStr}</td>
                    <td>{money(entry)}</td>
                    <td>{money(current)}</td>
                    <td className={pnlPos ? 'pos' : 'neg'}>{money(pos.unrealized_pl ?? 0)}</td>
                    <td className={pnlPos ? 'pos' : 'neg'}>{plPct >= 0 ? '+' : ''}{plPct.toFixed(2)}%</td>
                    <td>{money(stop)}</td>
                    <td>
                      {money(tp1)}&nbsp;
                      <span className="pill snap" style={{ marginLeft: 4 }}>VAP</span>
                    </td>
                    <td>{money(tp2)}</td>
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
