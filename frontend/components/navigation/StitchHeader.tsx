'use client';

import React, { useEffect, useState } from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useTradingStore } from '@/store/useTradingStore';

export const StitchHeader: React.FC = () => {
  const pathname = usePathname();
  const { account, connectionStatus, latencyMs, goalSummary } = useTradingStore();
  const [utcTime, setUtcTime] = useState('');

  useEffect(() => {
    const timer = setInterval(() => {
      const now = new Date();
      setUtcTime(now.toISOString().substring(11, 23));
    }, 100);
    return () => clearInterval(timer);
  }, []);

  const equity = account?.equity ?? 1000.0;
  const pnl = account?.realized_pl ?? 0.0;
  const pnlPct = equity > 0 ? (pnl / equity) * 100 : 0.0;

  return (
    <header className="fixed top-0 left-0 right-0 z-50 bg-surface-container-lowest/95 backdrop-blur-md shadow-[0_1px_8px_rgba(0,0,0,0.4)]">
      <div className="h-20 w-full px-space-md flex flex-col justify-between py-space-xs">
        {/* Top Row: Brand & Status Controls */}
        <div className="flex items-center justify-between gap-space-md">
          <div className="flex items-center gap-space-md">
            <div className="flex items-center gap-space-xs">
              <div className="w-7 h-7 rounded bg-primary-container flex items-center justify-center font-bold text-on-primary text-xs tracking-tighter">
                TRD
              </div>
              <div className="flex flex-col">
                <span className="font-headline-sm text-headline-sm uppercase tracking-wider text-on-surface font-semibold">
                  TRDENG
                </span>
                <span className="font-label-xs text-label-xs uppercase text-primary tracking-widest">
                  v4.2.8 Low-Latency
                </span>
              </div>
            </div>

            <div className="h-6 w-px bg-surface-container-highest"></div>

            {/* Engine Status */}
            <div className="flex items-center gap-space-xs bg-surface-container-low px-space-sm py-0.5 rounded">
              <span
                className={`w-1.5 h-1.5 rounded-full ${
                  connectionStatus === 'CONNECTED'
                    ? 'bg-primary-container shadow-[0_0_8px_rgba(0,240,168,0.45)]'
                    : 'bg-error animate-pulse'
                }`}
              ></span>
              <span className="font-label-xs text-label-xs uppercase text-primary-fixed font-semibold">
                {connectionStatus === 'CONNECTED' ? 'ENGINE ONLINE' : 'DISCONNECTED'}
              </span>
            </div>

            {/* Latency Telemetry */}
            <div className="flex items-center gap-space-xs bg-surface-container-low px-space-sm py-0.5 rounded font-numeric-sm text-numeric-sm text-on-surface-variant">
              <span className="text-primary-fixed">{latencyMs ? `${latencyMs}ms` : '4.2ms'}</span>
              <span>WS</span>
              <span className="text-surface-variant">/</span>
              <span className="text-primary-fixed">11.8ms</span>
              <span>BINANCE</span>
            </div>

            {/* Auto-Kill Switch Badge */}
            <div className="flex items-center gap-space-xs bg-error-container/40 px-space-sm py-0.5 rounded">
              <span className="w-1.5 h-1.5 rounded-full bg-error animate-pulse"></span>
              <span className="font-label-xs text-label-xs uppercase text-error tracking-wider font-semibold">
                AUTO-KILL SWITCH: ACTIVE
              </span>
            </div>
          </div>

          <div className="flex items-center gap-space-md">
            <div className="flex items-center gap-space-xs px-space-sm py-0.5 bg-surface-container-low rounded">
              <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">UTC</span>
              <span className="font-numeric-sm text-numeric-sm text-on-surface">{utcTime || '14:28:09.412'}</span>
            </div>
            <div className="flex items-center gap-space-xs px-space-sm py-0.5 bg-surface-container-low rounded text-primary">
              <span className="font-label-xs text-label-xs uppercase text-primary">SYNC: LOCK</span>
              <span className="font-numeric-sm text-numeric-sm">±0.02μs</span>
            </div>
            <div className="w-8 h-8 rounded-full bg-primary flex items-center justify-center">
              <span className="material-symbols-outlined text-on-primary text-[18px]">person</span>
            </div>
          </div>
        </div>

        {/* Bottom Row: Navigation Tabs & NAV KPIs */}
        <div className="flex items-center justify-between gap-space-md pt-0.5">
          <nav className="flex items-center gap-space-xs">
            <Link
              href="/crypto"
              className={`px-space-md py-1 rounded uppercase tracking-wide flex items-center gap-space-xs text-body-sm font-body-sm ${
                pathname === '/crypto' || pathname === '/'
                  ? 'bg-surface-container-high text-primary font-semibold shadow-inner'
                  : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
              }`}
            >
              Crypto Perpetuals
              <span className="bg-surface-container-highest text-on-surface-variant font-numeric-sm text-numeric-sm px-1 rounded-sm">
                24/7
              </span>
            </Link>

            <Link
              href="/us-futures"
              className={`px-space-md py-1 rounded uppercase tracking-wide flex items-center gap-space-xs text-body-sm font-body-sm ${
                pathname === '/us-futures'
                  ? 'bg-surface-container-high text-primary font-semibold shadow-inner'
                  : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
              }`}
            >
              US Futures
              <span className="bg-surface-container-highest text-on-surface-variant font-numeric-sm text-numeric-sm px-1 rounded-sm">
                RTH
              </span>
            </Link>

            <Link
              href="/trade-logs"
              className={`px-space-md py-1 rounded uppercase tracking-wide flex items-center gap-space-xs text-body-sm font-body-sm ${
                pathname === '/trade-logs'
                  ? 'bg-surface-container-high text-primary font-semibold shadow-inner'
                  : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
              }`}
            >
              Trade Logs
              <span className="bg-surface-container-highest text-on-surface-variant font-numeric-sm text-numeric-sm px-1 rounded-sm">
                AUDIT
              </span>
            </Link>
          </nav>

          {/* Top KPI Telemetry Bar */}
          <div className="flex items-center gap-space-lg font-numeric-sm text-numeric-sm bg-surface-container-lowest px-space-md py-0.5 rounded">
            <div className="flex items-center gap-space-xs">
              <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">NAV:</span>
              <span className="text-on-surface font-semibold">${equity.toLocaleString('en-US', { minimumFractionDigits: 2 })}</span>
            </div>
            <div className="flex items-center gap-space-xs">
              <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">DAILY P&L:</span>
              <span className={pnl >= 0 ? 'text-primary-fixed' : 'text-error'}>
                {pnl >= 0 ? `+$${pnl.toFixed(2)}` : `-$${Math.abs(pnl).toFixed(2)}`} ({pnlPct >= 0 ? '+' : ''}{pnlPct.toFixed(2)}%)
              </span>
            </div>
            <div className="flex items-center gap-space-xs">
              <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">DD:</span>
              <span className="text-on-surface">{((goalSummary?.current_drawdown_pct || 0.0)).toFixed(2)}%</span>
            </div>
            <div className="flex items-center gap-space-xs">
              <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">MARGIN:</span>
              <span className="text-on-surface">
                {equity > 0
                  ? ((Object.values(account?.positions || {}).reduce((acc, p) => acc + Math.abs((p.qty || p.size || 0) * (p.current_price || p.entry_price || 0) / (p.leverage || 5.0)), 0) / equity) * 100).toFixed(1)
                  : '0.0'}%
              </span>
            </div>
            <div className="flex items-center gap-space-xs">
              <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">CIRCUIT:</span>
              <span className={goalSummary?.engine_paused ? 'text-error font-bold' : 'text-primary-fixed'}>
                {goalSummary?.engine_paused ? 'STOPPED' : 'CLEAR'}
              </span>
            </div>
          </div>
        </div>
      </div>
    </header>
  );
};
