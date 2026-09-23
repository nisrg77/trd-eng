'use client';

import React, { useEffect, useRef, useState } from 'react';
import { createChart, IChartApi, ISeriesApi, CandlestickData, ColorType } from 'lightweight-charts';
import { useTradingStore } from '@/store/useTradingStore';

export const TradingViewChart: React.FC = () => {
  const chartContainerRef = useRef<HTMLDivElement>(null);
  const chartRef = useRef<IChartApi | null>(null);
  const candlestickSeriesRef = useRef<ISeriesApi<'Candlestick'> | null>(null);
  const volumeSeriesRef = useRef<ISeriesApi<'Histogram'> | null>(null);

  const historicalCandles = useTradingStore((state) => state.historicalCandles);
  const latestTick = useTradingStore((state) => state.latestTick);
  const selectedSymbol = useTradingStore((state) => state.selectedSymbol);

  const [activeTimeframe, setActiveTimeframe] = useState<string>('5s');

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const container = chartContainerRef.current;

    const chart = createChart(container, {
      width: container.clientWidth || 800,
      height: container.clientHeight || 420,
      layout: {
        background: { type: ColorType.Solid, color: '#090d16' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: 'rgba(30, 41, 59, 0.5)' },
        horzLines: { color: 'rgba(30, 41, 59, 0.5)' },
      },
      crosshair: {
        mode: 1,
        vertLine: {
          color: '#38bdf8',
          width: 1,
          style: 3,
        },
        horzLine: {
          color: '#38bdf8',
          width: 1,
          style: 3,
        },
      },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false,
      },
      handleScale: {
        axisPressedMouseMove: true,
        mouseWheel: true,
        pinch: true,
      },
      rightPriceScale: {
        borderColor: '#334155',
        autoScale: true,
        scaleMargins: {
          top: 0.1,
          bottom: 0.25,
        },
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: true,
        rightOffset: 5,
        barSpacing: 8,
      },
    });

    const candlestickSeries = chart.addCandlestickSeries({
      upColor: '#10b981',
      downColor: '#ef4444',
      borderVisible: false,
      wickUpColor: '#10b981',
      wickDownColor: '#ef4444',
    });

    const volumeSeries = chart.addHistogramSeries({
      color: '#3b82f6',
      priceFormat: { type: 'volume' },
      priceScaleId: '',
    });

    chart.priceScale('').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    });

    chartRef.current = chart;
    candlestickSeriesRef.current = candlestickSeries;
    volumeSeriesRef.current = volumeSeries;

    const resizeObserver = new ResizeObserver((entries) => {
      if (!entries || entries.length === 0) return;
      const { width, height } = entries[0].contentRect;
      if (width > 0 && height > 0) {
        chart.applyOptions({ width, height });
      }
    });

    resizeObserver.observe(container);

    return () => {
      resizeObserver.disconnect();
      chart.remove();
    };
  }, []);

  // Update initial historical data batch when symbol or candles change
  useEffect(() => {
    if (!candlestickSeriesRef.current || !volumeSeriesRef.current) return;

    if (historicalCandles.length === 0) return;

    // Deduplicate & sort candles by timestamp ascending (Lightweight Charts requirement)
    const sortedMap = new Map<number, typeof historicalCandles[0]>();
    for (const c of historicalCandles) {
      sortedMap.set(c.time, c);
    }
    const sortedCandles = Array.from(sortedMap.values()).sort((a, b) => a.time - b.time);

    const candleData: CandlestickData[] = sortedCandles.map((c) => ({
      time: c.time as any,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const volumeData = sortedCandles.map((c) => ({
      time: c.time as any,
      value: c.volume,
      color: c.close >= c.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
    }));

    candlestickSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);

    if (chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [historicalCandles, selectedSymbol]);

  // Real-time tick update using series.update() (mimics chart.md sample)
  useEffect(() => {
    if (!latestTick || !candlestickSeriesRef.current || !volumeSeriesRef.current) return;

    candlestickSeriesRef.current.update({
      time: latestTick.time as any,
      open: latestTick.open,
      high: latestTick.high,
      low: latestTick.low,
      close: latestTick.close,
    });

    volumeSeriesRef.current.update({
      time: latestTick.time as any,
      value: latestTick.volume,
      color: latestTick.close >= latestTick.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
    });
  }, [latestTick]);

  const handleScrollToRealtime = () => {
    if (chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  };

  return (
    <div className="relative w-full h-full min-h-[460px] bg-[#090d16] rounded-xl border border-slate-800/80 p-3 flex flex-col shadow-2xl overflow-hidden">
      {/* Header Bar: Symbol, Timeframe Selectors, OHLCV & Go-to-Realtime Control */}
      <div className="flex flex-wrap items-center justify-between px-3 py-2 border-b border-slate-800 mb-2 gap-2 flex-shrink-0 bg-slate-900/60 rounded-lg">
        <div className="flex items-center space-x-3">
          <span className="text-lg font-bold text-slate-100 font-mono tracking-tight">{selectedSymbol}</span>
          <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono font-semibold flex items-center gap-1.5">
            <span className="w-1.5 h-1.5 rounded-full bg-emerald-400 animate-pulse"></span>
            REALTIME FEED
          </span>
          <div className="h-4 w-px bg-slate-700"></div>
          <div className="flex items-center space-x-1">
            {['1s', '5s', '1m', '1h', '1d'].map((tf) => (
              <button
                key={tf}
                onClick={() => setActiveTimeframe(tf)}
                className={`px-2 py-0.5 text-xs rounded font-mono transition-colors ${
                  activeTimeframe === tf
                    ? 'bg-sky-500/20 text-sky-400 border border-sky-500/30 font-bold'
                    : 'text-slate-400 hover:text-slate-200 hover:bg-slate-800'
                }`}
              >
                {tf}
              </button>
            ))}
          </div>
        </div>

        <div className="flex items-center space-x-4">
          {latestTick && (
            <div className="flex items-center space-x-3 font-mono text-xs">
              <span className="text-slate-400">O: <strong className="text-slate-200">${latestTick.open.toFixed(2)}</strong></span>
              <span className="text-slate-400">H: <strong className="text-emerald-400">${latestTick.high.toFixed(2)}</strong></span>
              <span className="text-slate-400">L: <strong className="text-rose-400">${latestTick.low.toFixed(2)}</strong></span>
              <span className="text-slate-400">C: <strong className="text-slate-100 font-bold">${latestTick.close.toFixed(2)}</strong></span>
            </div>
          )}
          <button
            onClick={handleScrollToRealtime}
            className="px-3 py-1 text-xs rounded-md bg-slate-800 hover:bg-slate-700 text-slate-200 border border-slate-700 transition-all font-mono flex items-center space-x-1 font-semibold hover:border-slate-600 active:scale-95"
            title="Scroll to latest realtime data point"
          >
            <span>▶ Go to Realtime</span>
          </button>
        </div>
      </div>

      {/* Lightweight Charts Render Container */}
      <div ref={chartContainerRef} className="w-full flex-1 relative min-h-[390px] overflow-hidden rounded-lg" />
    </div>
  );
};
