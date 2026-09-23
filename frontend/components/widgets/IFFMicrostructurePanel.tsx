'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';

export const IFFMicrostructurePanel: React.FC = () => {
  const ms      = useTradingStore((s) => s.microstructure);
  const signals = useTradingStore((s) => s.signals);

  // iff_veto from latest crypto signal
  const latestCryptoSig = signals.find((s) =>
    /BTC|ETH|SOL|BNB|XRP|DOGE/i.test(s.instrument)
  ) as any;
  const iffVeto: boolean = latestCryptoSig?.iff_veto ?? false;

  function fmtPrice(n: number | null): React.ReactNode {
    if (n === null) return <span style={{ color: 'var(--tx3)' }}>â€”</span>;
    return '$' + n.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  }
  function fmtSigned(n: number | null): React.ReactNode {
    if (n === null || n === 0) return <span style={{ color: 'var(--tx3)' }}>â€”</span>;
    const pos = n >= 0;
    return <span className={pos ? 'pos' : 'neg'}>{pos ? '+' : ''}{n.toFixed(3)}</span>;
  }

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        Microstructure overlay&nbsp;
        <span className="badge purple">IFF</span>
        {iffVeto && <span className="badge red" style={{ marginLeft: 4 }}>VETO</span>}
        {!ms.iff_available && (
          <span className="badge amber" style={{ marginLeft: 4 }}>PENDING</span>
        )}
      </h2>

      <div className="micro-row">
        <div className="micro-item">
          <div className="l">VPOC</div>
          <div className="v">{fmtPrice(ms.vpoc_price)}</div>
        </div>
        <div className="micro-item">
          <div className="l">VAH</div>
          <div className="v">{fmtPrice(ms.vah)}</div>
        </div>
        <div className="micro-item">
          <div className="l">VAL</div>
          <div className="v">{fmtPrice(ms.val)}</div>
        </div>
        <div className="micro-item">
          <div className="l">CVD trend</div>
          <div className="v">{fmtSigned(ms.cvd_trend)}</div>
        </div>
        <div className="micro-item">
          <div className="l">Flow score</div>
          <div className="v">{fmtSigned(ms.flow_score)}</div>
        </div>
      </div>
    </div>
  );
};
