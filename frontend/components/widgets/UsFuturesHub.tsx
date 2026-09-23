'use client';

import React, { useEffect, useState } from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { getApiBaseUrl } from '@/lib/utils';

interface StockCandidate {
  rank: number;
  symbol: string;
  name: string;
  rvol: number;
  momentum: number;
  bias: 'LONG' | 'SHORT' | 'NEUTRAL';
}

interface ScreenerResponse {
  timestamp?: string | number;
  last_updated?: string | number;
  next_refresh?: string | number;
  expires_at?: string | number;
  cache_age_days?: number;
  ttl_days?: number;
  count?: number;
  source?: string;
  candidates?: any[];
  top_candidates?: any[];
}

const formatDate = (val: any): string => {
  if (!val) return 'Recent';
  if (typeof val === 'number') {
    try {
      const ms = val < 1e11 ? val * 1000 : val;
      return new Date(ms).toISOString().split('T')[0];
    } catch { return 'Recent'; }
  }
  if (typeof val === 'string') return val.includes('T') ? val.split('T')[0] : val.slice(0, 10);
  return 'Recent';
};

function pct(n: number, d = 1) {
  return (n >= 0 ? '+' : '') + (n * 100).toFixed(d) + '%';
}

export const UsFuturesHub: React.FC = () => {
  const screenerTargets = useTradingStore((s) => s.screenerTargets);

  const [screenerData, setScreenerData] = useState<ScreenerResponse | null>(null);
  const [loading, setLoading]           = useState(true);
  const [refreshing, setRefreshing]     = useState(false);

  const fetchCandidates = async () => {
    try {
      setLoading(true);
      const res = await fetch(`${getApiBaseUrl()}/api/screener/top-stocks`);
      if (res.ok) setScreenerData(await res.json());
    } catch (err) { console.error('Failed to load screener candidates:', err); }
    finally { setLoading(false); }
  };

  const handleRefreshCache = async () => {
    try {
      setRefreshing(true);
      const res = await fetch('http://localhost:8000/api/screener/refresh', { method: 'POST' });
      if (res.ok) setScreenerData(await res.json());
    } catch (err) { console.error('Error refreshing screener cache:', err); }
    finally { setRefreshing(false); }
  };

  useEffect(() => { fetchCandidates(); }, []);

  const rawCandidates = screenerData?.candidates || screenerData?.top_candidates || [];
  const candidates: StockCandidate[] = rawCandidates.map((c: any, idx: number) => {
    const isLong  = c.action === 'LONG' || c.bias === 'BUY'  || c.bias === 'LONG';
    const isShort = c.action === 'SHORT'|| c.bias === 'SELL' || c.bias === 'SHORT';
    return {
      rank:     c.rank ?? idx + 1,
      symbol:   c.symbol ?? '',
      name:     c.name || `${c.symbol} SSF Proxy`,
      rvol:     typeof c.rvol     === 'number' ? c.rvol     : 1.0,
      momentum: typeof c.momentum === 'number' ? c.momentum : 0.0,
      bias:     isLong ? 'LONG' : isShort ? 'SHORT' : 'NEUTRAL',
    };
  });

  const longCands  = candidates.filter((c) => c.bias === 'LONG');
  const shortCands = candidates.filter((c) => c.bias === 'SHORT');

  const scannedDate = formatDate(screenerData?.timestamp || screenerData?.last_updated);
  const cacheAgeDays =
    typeof screenerData?.cache_age_days === 'number'
      ? screenerData.cache_age_days.toFixed(1)
      : screenerData?.last_updated && typeof screenerData.last_updated === 'number'
      ? Math.max(0, (Date.now() / 1000 - (screenerData.last_updated as number)) / 86400).toFixed(1)
      : '0.1';
  const ttlDays = screenerData?.ttl_days ?? 7;

  return (
    <div
      className="rounded-xl p-4"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      {/* Header */}
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 10, flexWrap: 'wrap', gap: 8 }}>
        <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
          7-day screener candidates
          <span className="badge purple">7-DAY CACHED</span>
        </h2>
        <div style={{ display: 'flex', alignItems: 'center', gap: 10, fontSize: 11, color: 'var(--tx3)' }}>
          {screenerData && (
            <span>
              Scanned:&nbsp;<b style={{ color: 'var(--tx2)' }}>{scannedDate}</b>&nbsp;Â·&nbsp;
              Age:&nbsp;<b style={{ color: 'var(--cyan)' }}>{cacheAgeDays}d</b>/{ttlDays}d
            </span>
          )}
          <button
            onClick={handleRefreshCache}
            disabled={refreshing}
            style={{
              fontSize: 11,
              padding: '4px 10px',
              borderRadius: 7,
              border: '1px solid rgba(6,182,212,.3)',
              background: 'rgba(6,182,212,.1)',
              color: 'var(--cyan)',
              cursor: 'pointer',
              opacity: refreshing ? 0.5 : 1,
            }}
            title="Force-refresh 7-day cache"
          >
            {refreshing ? 'â³ Analyzingâ€¦' : 'ðŸ”„ Refresh Cache'}
          </button>
        </div>
      </div>

      {loading ? (
        <div style={{ padding: '14px 0', color: 'var(--tx3)', fontSize: 12 }}>Loading candidatesâ€¦</div>
      ) : (
        <div style={{ display: 'grid', gridTemplateColumns: '1fr 1fr', gap: 14 }}>
          {/* Long candidates */}
          <div>
            <div className="subtle" style={{ marginBottom: 8 }}>Long candidates</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {longCands.length === 0 ? (
                <span className="subtle">None ranked yet.</span>
              ) : (
                longCands.map((c) => (
                  <span key={c.symbol} className="cand long" title={c.name}>
                    {c.symbol} Â· mom {pct(c.momentum)} Â· rvol {c.rvol.toFixed(2)}
                    {(screenerTargets?.long === c.symbol) && ' â˜…'}
                  </span>
                ))
              )}
            </div>
          </div>

          {/* Short candidates */}
          <div>
            <div className="subtle" style={{ marginBottom: 8 }}>Short candidates</div>
            <div style={{ display: 'flex', flexWrap: 'wrap', gap: 6 }}>
              {shortCands.length === 0 ? (
                <span className="subtle">None ranked yet.</span>
              ) : (
                shortCands.map((c) => (
                  <span key={c.symbol} className="cand short" title={c.name}>
                    {c.symbol} Â· mom {pct(c.momentum)} Â· rvol {c.rvol.toFixed(2)}
                    {(screenerTargets?.short === c.symbol) && ' â˜…'}
                  </span>
                ))
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};

