'use client';

import React, { useState, useEffect, useCallback } from 'react';
import { useTradingStore } from '@/store/useTradingStore';
import { getApiBaseUrl } from '@/lib/utils';

interface StockCandidate {
  rank: number;
  symbol: string;
  rvol: number;
  momentum: number;
  bias: 'BUY' | 'SELL' | 'NEUTRAL';
  action: 'LONG' | 'SHORT' | 'HOLD';
  price?: number;
}

export const StockScreenerCard: React.FC = () => {
  const selectedSymbol = useTradingStore((state) => state.selectedSymbol);
  const setSelectedSymbol = useTradingStore((state) => state.setSelectedSymbol);

  const [candidates, setCandidates] = useState<StockCandidate[]>([]);
  const [filter, setFilter] = useState<'ALL' | 'LONG' | 'SHORT'>('ALL');
  const [isLoading, setIsLoading] = useState<boolean>(false);
  const [lastUpdatedTime, setLastUpdatedTime] = useState<string>('');
  const [secondsRemaining, setSecondsRemaining] = useState<number>(900); // 15 mins = 900s

  const fetchScreenerData = useCallback(async (force: boolean = false) => {
    try {
      setIsLoading(true);
      const baseUrl = getApiBaseUrl();
      const url = force
        ? `${baseUrl}/api/screener/refresh`
        : `${baseUrl}/api/screener/top-stocks`;
      
      const res = await fetch(url, force ? { method: 'POST' } : { method: 'GET' });
      if (res.ok) {
        const data = await res.json();
        const topList: StockCandidate[] = data.top_candidates || data.candidates || [];
        setCandidates(topList);
        
        const now = new Date();
        setLastUpdatedTime(now.toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit', second: '2-digit' }));
        setSecondsRemaining(900); // Reset 15 min countdown
      }
    } catch (err) {
      console.error('Failed to fetch screener top stocks:', err);
    } finally {
      setIsLoading(false);
    }
  }, []);

  // Initial fetch on mount
  useEffect(() => {
    fetchScreenerData(false);
  }, [fetchScreenerData]);

  // 15-minute countdown interval
  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsRemaining((prev) => {
        if (prev <= 1) {
          fetchScreenerData(false);
          return 900;
        }
        return prev - 1;
      });
    }, 1000);

    return () => clearInterval(timer);
  }, [fetchScreenerData]);

  const formatCountdown = (secs: number) => {
    const m = Math.floor(secs / 60);
    const s = secs % 60;
    return `${m.toString().padStart(2, '0')}:${s.toString().padStart(2, '0')}`;
  };

  const filteredCandidates = candidates.filter((c) => {
    if (filter === 'LONG') return c.action === 'LONG' || c.bias === 'BUY';
    if (filter === 'SHORT') return c.action === 'SHORT' || c.bias === 'SELL';
    return true;
  });

  return (
    <div className="w-full bg-[#090d16] rounded-xl border border-slate-800/80 p-4 shadow-xl flex flex-col gap-3">
      {/* Card Header & Controls */}
      <div className="flex flex-wrap items-center justify-between gap-2 pb-3 border-b border-slate-800">
        <div className="flex items-center space-x-3">
          <div className="flex items-center space-x-2">
            <span className="w-2.5 h-2.5 rounded-full bg-cyan-400 animate-pulse"></span>
            <h3 className="text-sm font-bold uppercase tracking-wider text-slate-100 font-mono">
              TradingView 15-Min Top Stock Screener
            </h3>
          </div>
          <span className="px-2 py-0.5 rounded bg-cyan-500/10 text-cyan-400 border border-cyan-500/20 text-[11px] font-mono font-semibold">
            7-DAY MOMENTUM + RVOL
          </span>
        </div>

        <div className="flex items-center space-x-3 text-xs font-mono">
          {/* 15-Min Auto Update Timer Badge */}
          <div className="flex items-center space-x-1.5 px-2.5 py-1 rounded-md bg-slate-900 border border-slate-700/60 text-slate-300">
            <span className="text-slate-400">Auto-Update:</span>
            <span className="text-cyan-400 font-bold">{formatCountdown(secondsRemaining)}</span>
          </div>

          {/* Filter Pills */}
          <div className="flex items-center bg-slate-900 p-0.5 rounded-lg border border-slate-800">
            <button
              onClick={() => setFilter('ALL')}
              className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                filter === 'ALL'
                  ? 'bg-cyan-500/20 text-cyan-300 border border-cyan-500/30 font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              ALL ({candidates.length})
            </button>
            <button
              onClick={() => setFilter('LONG')}
              className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                filter === 'LONG'
                  ? 'bg-emerald-500/20 text-emerald-400 border border-emerald-500/30 font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              BULLISH
            </button>
            <button
              onClick={() => setFilter('SHORT')}
              className={`px-2.5 py-1 rounded-md text-[11px] font-semibold transition-all ${
                filter === 'SHORT'
                  ? 'bg-rose-500/20 text-rose-400 border border-rose-500/30 font-bold'
                  : 'text-slate-400 hover:text-slate-200'
              }`}
            >
              BEARISH
            </button>
          </div>

          {/* Refresh Button */}
          <button
            onClick={() => fetchScreenerData(true)}
            disabled={isLoading}
            className="px-3 py-1 rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-all font-semibold flex items-center space-x-1 disabled:opacity-50"
            title="Force refresh stock screener rankings"
          >
            <span className={isLoading ? 'animate-spin' : ''}>🔄</span>
            <span>{isLoading ? 'Updating...' : 'Refresh'}</span>
          </button>
        </div>
      </div>

      {/* Timestamp & Info Bar */}
      <div className="flex items-center justify-between text-[11px] font-mono text-slate-400">
        <span>Evaluates 55 CME Single Stock Futures (SSF) proxies by intraday volume spike & momentum</span>
        {lastUpdatedTime && <span>Last Updated: <strong className="text-slate-200">{lastUpdatedTime}</strong></span>}
      </div>

      {/* Grid of Stock Screener Cards */}
      <div className="grid grid-cols-1 sm:grid-cols-2 md:grid-cols-3 lg:grid-cols-5 gap-3">
        {filteredCandidates.map((c) => {
          const isSelected = selectedSymbol === c.symbol;
          const isBull = c.action === 'LONG' || c.bias === 'BUY';
          const momentumPct = (c.momentum * 100).toFixed(2);
          const isPosMom = c.momentum >= 0;

          return (
            <div
              key={c.symbol}
              onClick={() => setSelectedSymbol(c.symbol as any)}
              className={`group relative p-3 rounded-lg border transition-all cursor-pointer flex flex-col justify-between ${
                isSelected
                  ? 'bg-gradient-to-b from-cyan-950/40 to-slate-900 border-cyan-500 shadow-lg shadow-cyan-500/10 scale-[1.02]'
                  : isBull
                  ? 'bg-slate-900/60 border-slate-800 hover:border-emerald-500/50 hover:bg-slate-800/60'
                  : 'bg-slate-900/60 border-slate-800 hover:border-rose-500/50 hover:bg-slate-800/60'
              }`}
            >
              {/* Card Top: Rank & Ticker & Action Badge */}
              <div className="flex items-center justify-between mb-2">
                <div className="flex items-center space-x-1.5">
                  <span className="text-[10px] font-mono font-bold px-1.5 py-0.5 rounded bg-slate-800 text-slate-400">
                    #{c.rank}
                  </span>
                  <span className="text-sm font-mono font-bold text-slate-100 group-hover:text-cyan-400">
                    {c.symbol}
                  </span>
                </div>
                <span
                  className={`text-[10px] font-mono font-bold px-2 py-0.5 rounded border ${
                    isBull
                      ? 'bg-emerald-500/10 text-emerald-400 border-emerald-500/30'
                      : 'bg-rose-500/10 text-rose-400 border-rose-500/30'
                  }`}
                >
                  {c.action || (isBull ? 'LONG' : 'SHORT')}
                </span>
              </div>

              {/* Card Middle: Key Screener Metrics */}
              <div className="grid grid-cols-2 gap-2 my-1 font-mono text-xs">
                <div className="bg-slate-950/50 p-1.5 rounded border border-slate-800/50">
                  <span className="text-[10px] text-slate-400 block">RVOL</span>
                  <span className="font-bold text-slate-200">{c.rvol}x</span>
                </div>
                <div className="bg-slate-950/50 p-1.5 rounded border border-slate-800/50">
                  <span className="text-[10px] text-slate-400 block">MOMENTUM</span>
                  <span className={`font-bold ${isPosMom ? 'text-emerald-400' : 'text-rose-400'}`}>
                    {isPosMom ? `+${momentumPct}%` : `${momentumPct}%`}
                  </span>
                </div>
              </div>

              {/* Card Footer: View Chart Button */}
              <div className="mt-2 pt-2 border-t border-slate-800/60 flex items-center justify-between">
                <span className="text-[10px] font-mono text-slate-400">
                  {isSelected ? 'ACTIVE CHART' : 'Click to load'}
                </span>
                <button
                  onClick={(e) => {
                    e.stopPropagation();
                    setSelectedSymbol(c.symbol as any);
                  }}
                  className={`px-2 py-0.5 text-[10px] font-mono font-bold rounded transition-all ${
                    isSelected
                      ? 'bg-cyan-500 text-slate-950 font-extrabold shadow-sm'
                      : 'bg-slate-800 text-slate-300 hover:bg-slate-700 hover:text-white'
                  }`}
                >
                  {isSelected ? '✓ VIEWING' : 'VIEW CHART →'}
                </button>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
};
