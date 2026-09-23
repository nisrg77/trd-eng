'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import type { MLSignal } from '@/types/trading';

interface MLSignalPanelProps {
  market: 'us' | 'crypto';
}

const REGIME_LABELS: Record<string, string> = {
  trending_up:    'trending up',
  high_volatility:'high volatility',
  low_volatility: 'low volatility',
  neutral:        'neutral',
};

export const MLSignalPanel: React.FC<MLSignalPanelProps> = ({ market }) => {
  const signals = useTradingStore((s) => s.signals);

  // Latest signal for this market (instrument prefix heuristic)
  const sig: MLSignal | undefined = signals.find((s) =>
    market === 'crypto'
      ? /BTC|ETH|SOL|BNB|XRP|DOGE/i.test(s.instrument)
      : !/BTC|ETH|SOL|BNB|XRP|DOGE/i.test(s.instrument)
  );

  const dir   = sig?.direction_magnitude ?? 0;
  const conf  = sig?.confidence_score    ?? 0;
  const regime = REGIME_LABELS[sig?.regime_flag ?? 'neutral'] ?? (sig?.regime_flag ?? 'neutral');

  // needle position: dir in [-1,1] → 0%–100%
  const needlePct = ((dir + 1) / 2) * 100;

  const weights = sig?.weights_used ?? { ridge: 0.35, xgb: 0.35, lstm: 0.30 };
  const models: [string, number][] = Object.entries(sig?.per_model ?? { ridge: 0, xgb: 0, lstm: 0 });

  const badgeCls = market === 'us' ? 'amber' : 'amber';

  return (
    <div
      className="rounded-xl p-4 flex flex-col gap-3"
      style={{ background: 'var(--card)', border: '1px solid var(--border)' }}
    >
      <h2 style={{ fontSize: 14, fontWeight: 600, margin: 0, display: 'flex', alignItems: 'center', gap: 8 }}>
        ML signal&nbsp;
        <span className={`badge ${badgeCls}`} id={`${market}-regime`}>{regime}</span>
      </h2>

      {/* Gauge */}
      <div className="flex items-center gap-4">
        <div className="needle-track" style={{ flex: 1 }}>
          <div className="needle" style={{ left: `${needlePct}%` }} />
        </div>
      </div>

      <div className="subtle">
        Direction:&nbsp;
        <b style={{ color: dir >= 0 ? 'var(--green)' : 'var(--red)' }}>
          {dir >= 0 ? 'Buy ' : 'Sell '}{Math.abs(dir).toFixed(3)}
        </b>
        &nbsp;·&nbsp;Confidence:&nbsp;
        <b>{(conf * 100).toFixed(1)}%</b>
      </div>

      {/* Per-model bars */}
      <div>
        {models.map(([key, val]) => {
          const w      = Math.round((weights as any)[key] * 100);
          const width  = Math.abs(val) * 50;
          const left   = val >= 0 ? 50 : 50 - width;
          const isBear = val < 0;
          return (
            <div key={key} className="modelbar">
              <div className="lbl">{key}</div>
              <div className="track">
                <div
                  className={`fill${isBear ? ' bear' : ''}`}
                  style={{ left: `${left}%`, width: `${width}%` }}
                />
              </div>
              <div className="pct">{val.toFixed(3)} ({w}%)</div>
            </div>
          );
        })}
        {models.length === 0 && (
          <div className="subtle" style={{ padding: '6px 0' }}>Waiting for live signals…</div>
        )}
      </div>
    </div>
  );
};
