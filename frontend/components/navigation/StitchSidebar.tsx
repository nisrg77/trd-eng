'use client';

import React from 'react';
import Link from 'next/link';
import { usePathname } from 'next/navigation';

export const StitchSidebar: React.FC = () => {
  const pathname = usePathname();

  return (
    <aside className="fixed left-0 top-20 bottom-0 w-60 bg-surface-container-low z-40 flex flex-col justify-between py-space-md px-space-xs border-r border-surface-container-high/60">
      <div className="flex flex-col gap-space-sm">
        <div className="px-space-sm py-1 font-label-xs text-label-xs uppercase text-on-surface-variant tracking-wider">
          Execution Modules
        </div>
        <nav className="flex flex-col gap-0.5">
          <Link
            href="/crypto"
            className={`px-space-sm py-space-sm rounded font-body-sm text-body-sm flex items-center justify-between ${
              pathname === '/crypto' || pathname === '/'
                ? 'bg-surface-container-high text-primary font-semibold'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
          >
            <span>Crypto Perpetuals</span>
            <span className="font-numeric-sm text-numeric-sm text-primary">LIVE 24/7</span>
          </Link>

          <Link
            href="/us-futures"
            className={`px-space-sm py-space-sm rounded font-body-sm text-body-sm flex items-center justify-between ${
              pathname === '/us-futures'
                ? 'bg-surface-container-high text-primary font-semibold'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
          >
            <span>US Stock Futures</span>
            <span className="font-numeric-sm text-numeric-sm text-on-surface-variant">RTH HUB</span>
          </Link>

          <Link
            href="/trade-logs"
            className={`px-space-sm py-space-sm rounded font-body-sm text-body-sm flex items-center justify-between ${
              pathname === '/trade-logs'
                ? 'bg-surface-container-high text-primary font-semibold'
                : 'text-on-surface-variant hover:bg-surface-container hover:text-on-surface'
            }`}
          >
            <span>Execution Audit & Fills</span>
            <span className="font-numeric-sm text-numeric-sm text-on-surface-variant">AUDIT</span>
          </Link>
        </nav>

        <div className="h-px bg-surface-container-highest my-space-xs"></div>

        <div className="px-space-sm py-1 font-label-xs text-label-xs uppercase text-on-surface-variant tracking-wider">
          Gateway Status
        </div>
        <div className="px-space-sm flex flex-col gap-1.5 font-label-xs text-label-xs">
          <div className="flex justify-between items-center text-on-surface-variant">
            <span>CME Globex (iLink3)</span>
            <span className="text-primary-fixed">CONNECTED</span>
          </div>
          <div className="flex justify-between items-center text-on-surface-variant">
            <span>Binance Futures FIX</span>
            <span className="text-primary-fixed">CONNECTED</span>
          </div>
          <div className="flex justify-between items-center text-on-surface-variant">
            <span>Alpaca Market Data</span>
            <span className="text-primary-fixed">CONNECTED</span>
          </div>
          <div className="flex justify-between items-center text-on-surface-variant">
            <span>Risk Guard Overlay</span>
            <span className="text-primary-fixed">ACTIVE</span>
          </div>
        </div>
      </div>

      <div className="p-space-sm bg-surface-container rounded flex flex-col gap-1">
        <div className="flex justify-between items-center">
          <span className="font-label-xs text-label-xs uppercase text-on-surface-variant">ENGINE BUFFER</span>
          <span className="font-numeric-sm text-numeric-sm text-primary">31%</span>
        </div>
        <div className="w-full h-1 bg-surface-container-highest rounded overflow-hidden">
          <div className="h-full bg-primary" style={{ width: '31%' }}></div>
        </div>
        <div className="flex justify-between items-center font-label-xs text-label-xs text-on-surface-variant pt-1">
          <span>CPU: 4.80GHz</span>
          <span>TEMP: 49°C</span>
        </div>
      </div>
    </aside>
  );
};
