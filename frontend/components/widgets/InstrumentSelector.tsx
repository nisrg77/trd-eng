'use client';

import React, { useState, useEffect, useRef } from 'react';
import { useTradingStore } from '@/store/useTradingStore';

const CORE_SYMBOLS = ['BTC-USD', 'ETH-USD', 'SPY', 'AAPL'];

interface SearchResult {
  symbol: string;
  name: string;
  type: string;
}

export const InstrumentSelector: React.FC = () => {
  const selectedSymbol = useTradingStore((state) => state.selectedSymbol);
  const setSelectedSymbol = useTradingStore((state) => state.setSelectedSymbol);
  const connectionStatus = useTradingStore((state) => state.connectionStatus);

  const [query, setQuery] = useState('');
  const [results, setResults] = useState<SearchResult[]>([]);
  const [isOpen, setIsOpen] = useState(false);
  const [isSearching, setIsSearching] = useState(false);
  const dropdownRef = useRef<HTMLDivElement>(null);

  // Close search dropdown on click outside
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      if (dropdownRef.current && !dropdownRef.current.contains(e.target as Node)) {
        setIsOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClickOutside);
    return () => document.removeEventListener('mousedown', handleClickOutside);
  }, []);

  // Debounced search query to backend /api/stocks/search
  useEffect(() => {
    if (!query.trim()) {
      setResults([]);
      setIsOpen(false);
      return;
    }

    const timer = setTimeout(async () => {
      try {
        setIsSearching(true);
        const res = await fetch(`http://localhost:8000/api/stocks/search?q=${encodeURIComponent(query)}`);
        if (res.ok) {
          const data = await res.json();
          setResults(data.results || []);
          setIsOpen(true);
        }
      } catch (err) {
        console.error('Error searching stocks:', err);
      } finally {
        setIsSearching(false);
      }
    }, 200);

    return () => clearTimeout(timer);
  }, [query]);

  const handleSelectSymbol = (symbol: string) => {
    setSelectedSymbol(symbol);
    setQuery('');
    setIsOpen(false);
  };

  // Symbols list includes core symbols + currently selected symbol if not already present
  const displaySymbols = Array.from(new Set([...CORE_SYMBOLS, selectedSymbol]));

  return (
    <div className="flex flex-wrap items-center gap-3">
      {/* Quick Select Buttons */}
      <div className="flex items-center bg-[#090d16] border border-slate-800 rounded-lg p-1">
        {displaySymbols.map((sym) => (
          <button
            key={sym}
            onClick={() => setSelectedSymbol(sym)}
            className={`px-3 py-1.5 text-xs font-semibold font-mono rounded-md transition-all ${
              selectedSymbol === sym
                ? 'bg-gradient-to-r from-cyan-600 to-blue-600 text-white shadow-md shadow-cyan-500/20'
                : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800/50'
            }`}
          >
            {sym}
          </button>
        ))}
      </div>

      {/* Stock & Future Search Bar */}
      <div className="relative" ref={dropdownRef}>
        <div className="flex items-center bg-[#090d16] border border-slate-800 rounded-lg px-2.5 py-1 focus-within:border-cyan-500/80 transition-all">
          <span className="text-slate-400 text-xs mr-2">🔍</span>
          <input
            type="text"
            placeholder="Search stock / future..."
            value={query}
            onChange={(e) => setQuery(e.target.value)}
            onFocus={() => query.trim() && setIsOpen(true)}
            className="bg-transparent text-xs font-mono text-slate-100 placeholder:text-slate-500 focus:outline-none w-36 sm:w-44"
          />
          {isSearching && (
            <span className="text-[10px] text-cyan-400 animate-spin mr-1">⌛</span>
          )}
          {query && (
            <button
              onClick={() => {
                setQuery('');
                setIsOpen(false);
              }}
              className="text-slate-500 hover:text-slate-300 text-xs ml-1"
            >
              ✕
            </button>
          )}
        </div>

        {/* Autocomplete Dropdown */}
        {isOpen && (
          <div className="absolute left-0 mt-1 w-64 bg-[#090d16] border border-slate-700/80 rounded-lg shadow-2xl z-50 overflow-hidden max-h-60 overflow-y-auto">
            <div className="p-1.5 text-[10px] font-mono text-slate-500 border-b border-slate-800 flex justify-between">
              <span>SEARCH RESULTS</span>
              <span>{results.length} FOUND</span>
            </div>
            {results.length === 0 ? (
              <div className="p-3 text-center text-xs text-slate-500 font-mono">
                No matching symbols
              </div>
            ) : (
              results.map((r) => (
                <button
                  key={r.symbol}
                  onClick={() => handleSelectSymbol(r.symbol)}
                  className="w-full text-left px-3 py-2 hover:bg-slate-800/80 transition-colors flex items-center justify-between group border-b border-slate-800/30 last:border-b-0"
                >
                  <div className="flex flex-col">
                    <span className="text-xs font-mono font-bold text-white group-hover:text-cyan-400">
                      {r.symbol}
                    </span>
                    <span className="text-[10px] text-slate-400 truncate max-w-[170px]">
                      {r.name}
                    </span>
                  </div>
                  <span className="text-[9px] font-mono text-slate-400 bg-slate-800 px-1.5 py-0.5 rounded">
                    {r.type}
                  </span>
                </button>
              ))
            )}
          </div>
        )}
      </div>

      {/* Connection Status Badge */}
      <div className="flex items-center space-x-2 px-3 py-1.5 rounded-lg bg-[#090d16] border border-slate-800 text-xs font-mono">
        <span
          className={`h-2.5 w-2.5 rounded-full ${
            connectionStatus === 'CONNECTED'
              ? 'bg-emerald-400 animate-pulse'
              : connectionStatus === 'RECONNECTING'
              ? 'bg-amber-400 animate-ping'
              : 'bg-rose-500'
          }`}
        />
        <span className="text-slate-300 font-semibold">{connectionStatus}</span>
      </div>
    </div>
  );
};
