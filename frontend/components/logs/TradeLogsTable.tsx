'use client';

import React, { useState, useMemo } from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import type { OrderExecution } from '@/types/trading';

type FilterKey = 'all' | 'us' | 'crypto' | 'rejected';
type SortKey   = keyof OrderExecution | 'market';

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

export const TradeLogsTable: React.FC = () => {
  const executions = useTradingStore((s) => s.executions);

  const [filter, setFilter] = useState<FilterKey>('all');
  const [sortKey, setSortKey] = useState<string>('timestamp_proposed');
  const [sortDir, setSortDir] = useState<1 | -1>(-1);

  const FILTERS: { key: FilterKey; label: string }[] = [
    { key: 'all',      label: 'All markets'    },
    { key: 'us',       label: 'US only'        },
    { key: 'crypto',   label: 'Crypto only'    },
    { key: 'rejected', label: 'Rejected only'  },
  ];

  const filtered = useMemo(() => {
    let rows = [...executions];
    if (filter === 'us')       rows = rows.filter((r) => !isCrypto(r.instrument));
    if (filter === 'crypto')   rows = rows.filter((r) =>  isCrypto(r.instrument));
    if (filter === 'rejected') rows = rows.filter((r) =>  r.risk_state === 'REJECTED');
    rows.sort((a, b) => {
      const va = (a as any)[sortKey];
      const vb = (b as any)[sortKey];
      const cmp = typeof va === 'string' ? va.localeCompare(vb) : (va ?? 0) - (vb ?? 0);
      return cmp * sortDir;
    });
    return rows;
  }, [executions, filter, sortKey, sortDir]);

  function handleSort(key: string) {
    if (sortKey === key) setSortDir((d) => (d === 1 ? -1 : 1));
    else { setSortKey(key); setSortDir(-1); }
  }

  const COLS: { label: string; key: string }[] = [
    { label: 'Time',       key: 'timestamp_proposed' },
    { label: 'Instrument', key: 'instrument'         },
    { label: 'Action',     key: 'action'             },
    { label: 'Type',       key: 'order_type'         },
    { label: 'Alloc %',    key: 'portfolio_allocation_pct' },
    { label: 'Risk state', key: 'risk_state'         },
    { label: 'OMS',        key: 'oms_state'          },
    { label: 'Realized P/L', key: 'notional_value'  },
  ];

  return (
    <div
      className="rounded-xl p-4"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      <h2 style={{ fontSize: 14, fontWeight: 600, margin: '0 0 10px' }}>
        Execution &amp; risk audit log
      </h2>

      {/* Filters */}
      <div style={{ display: 'flex', gap: 6, marginBottom: 10, flexWrap: 'wrap' }}>
        {FILTERS.map(({ key, label }) => (
          <button
            key={key}
            onClick={() => setFilter(key)}
            style={{
              fontSize: 12,
              padding: '5px 11px',
              borderRadius: 8,
              border: `1px solid ${filter === key ? 'var(--blue)' : 'var(--border)'}`,
              background: filter === key ? 'var(--blue)' : 'var(--card2)',
              color: filter === key ? '#fff' : 'var(--tx2)',
              cursor: 'pointer',
            }}
          >
            {label}
          </button>
        ))}
      </div>

      {/* Table */}
      <div style={{ overflowX: 'auto' }}>
        <table style={{ minWidth: 800 }}>
          <thead>
            <tr>
              {COLS.map(({ label, key }) => (
                <th
                  key={key}
                  onClick={() => handleSort(key)}
                  style={{ cursor: 'pointer', userSelect: 'none' }}
                  title={`Sort by ${label}`}
                >
                  {label} {sortKey === key ? (sortDir === -1 ? '↓' : '↑') : ''}
                </th>
              ))}
            </tr>
          </thead>
          <tbody>
            {filtered.length === 0 ? (
              <tr>
                <td colSpan={COLS.length} style={{ textAlign: 'center', padding: '20px 0', color: 'var(--tx3)' }}>
                  {executions.length === 0
                    ? 'No execution logs yet — engine is running…'
                    : 'No entries match the filter.'}
                </td>
              </tr>
            ) : (
              filtered.map((ex) => {
                const crypto = isCrypto(ex.instrument);
                const isBuy  = ex.action === 'BUY';
                const approved = ex.risk_state === 'APPROVED';
                const filled   = ex.oms_state === 'FILLED' || ex.oms_state === 'SUBMITTED';
                const pnl      = ex.notional_value ?? 0;

                return (
                  <tr key={ex.order_id}>
                    <td>{fmtDate(ex.timestamp_proposed)}</td>
                    <td>
                      <b>{ex.instrument}</b>
                      &nbsp;
                      <span className={`badge ${crypto ? 'cyan' : 'blue'}`} style={{ marginLeft: 4 }}>
                        {crypto ? 'crypto' : 'us'}
                      </span>
                    </td>
                    <td>
                      <span className={`pill ${isBuy ? 'long' : 'short'}`}>{ex.action}</span>
                    </td>
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
                    <td>{ex.oms_state}{ex.oms_detail ? ` (${ex.oms_detail})` : ''}</td>
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
