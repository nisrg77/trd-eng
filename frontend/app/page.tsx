'use client';

import React from 'react';
import { useTradingWebSocket } from '@/hooks/useTradingWebSocket';
import { PerformanceWidgets } from '@/components/widgets/PerformanceWidgets';
import { TradingViewChart } from '@/components/charts/TradingViewChart';
import { EquityCurveChart } from '@/components/charts/EquityCurveChart';
import { OrderBookComponent } from '@/components/orderbook/OrderBook';
import { BottomPanel } from '@/components/logs/BottomPanel';
import { InstrumentSelector } from '@/components/widgets/InstrumentSelector';

export default function DashboardPage() {
  // Connect to FastAPI WebSocket streaming bridge
  useTradingWebSocket();

  return (
    <div className="min-h-screen bg-[#05080f] text-slate-100 flex flex-col p-4 space-y-4 font-sans max-w-[1920px] mx-auto">
      {/* Top Navigation & Status Bar */}
      <header className="flex flex-col md:flex-row items-start md:items-center justify-between pb-3 border-b border-slate-800/80 gap-3">
        <div className="flex items-center space-x-3">
          <div className="h-9 w-9 bg-gradient-to-tr from-cyan-500 to-emerald-500 rounded-xl flex items-center justify-center font-black text-black shadow-lg shadow-cyan-500/20 text-lg">
            ⚡
          </div>
          <div>
            <h1 className="text-xl font-black tracking-tight text-white flex items-center gap-2">
              TEDENG <span className="text-[10px] px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 font-mono font-semibold">QUANT ENGINE v2.4</span>
            </h1>
            <p className="text-xs text-slate-400">High-Frequency ML Algorithmic Trading Workspace</p>
          </div>
        </div>

        <InstrumentSelector />
      </header>

      {/* Real-time Summary Performance Metric Cards */}
      <PerformanceWidgets />

      {/* Main Viewport Grid */}
      <main className="grid grid-cols-1 lg:grid-cols-12 gap-4 flex-1">
        {/* Left Column: Candlestick Chart + Equity Curve */}
        <div className="lg:col-span-9 flex flex-col space-y-4">
          <div className="h-[460px] w-full">
            <TradingViewChart />
          </div>
          <div className="h-[220px] w-full">
            <EquityCurveChart />
          </div>
        </div>

        {/* Right Column: Order Book & Depth Sidebar */}
        <div className="lg:col-span-3 h-[696px]">
          <OrderBookComponent />
        </div>
      </main>

      {/* Bottom Control & Logs Panel */}
      <footer className="w-full pt-2">
        <BottomPanel />
      </footer>
    </div>
  );
}
