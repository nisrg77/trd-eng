'use client';

import React from 'react';
import { useTradingStore } from '@/store/useTradingStore';

interface KpiCardsProps {
  /** 'us' or 'crypto' — controls which drawdown limit label to show (3% vs 6%) */
  market: 'us' | 'crypto';
}

function money(n: number, decimals = 2) {
  const abs = Math.abs(n).toLocaleString(undefined, {
    minimumFractionDigits: decimals,
    maximumFractionDigits: decimals,
  });
  return (n < 0 ? '-' : '') + '$' + abs;
}

export const KpiCards: React.FC<KpiCardsProps> = ({ market }) => {
  const account = useTradingStore((s) => s.account);

  const equity        = account.equity       ?? 1000;
  const balance       = account.balance      ?? 1000;
  const realizedPL    = account.realized_pl  ?? 0;
  const buyingPower   = account.gross_buying_power ?? equity * 10;
  const ddPct         = account.active_drawdown_pct ?? 0;
  const ddLimit       = market === 'us' ? 3.0 : 6.0;
  const ddPctOfLimit  = Math.min(100, (ddPct / ddLimit) * 100);
  const ddDanger      = ddPctOfLimit > 75;

  const plPos = realizedPL >= 0;

  return (
    <div className="grid gap-2.5" style={{ gridTemplateColumns: 'repeat(auto-fit,minmax(150px,1fr))' }}>
      {/* Equity */}
      <div className="kpi">
        <div className="l">Equity (NLV)</div>
        <div className="v">{money(equity)}</div>
      </div>

      {/* Balance */}
      <div className="kpi">
        <div className="l">Balance</div>
        <div className="v">{money(balance)}</div>
      </div>

      {/* Realized P/L */}
      <div className="kpi">
        <div className="l">Realized P/L</div>
        <div className={`v ${plPos ? 'pos' : 'neg'}`}>{money(realizedPL)}</div>
      </div>

      {/* Buying Power */}
      <div className="kpi">
        <div className="l">Buying power</div>
        <div className="v">{money(buyingPower, 0)}</div>
      </div>

      {/* Drawdown with bar */}
      <div className="kpi">
        <div className="l">Drawdown vs {ddLimit}% limit</div>
        <div className="v">{ddPct.toFixed(2)}%</div>
        <div className="dd-bar">
          <div
            className={`dd-fill${ddDanger ? ' danger' : ''}`}
            style={{ width: `${ddPctOfLimit}%` }}
          />
        </div>
      </div>
    </div>
  );
};
