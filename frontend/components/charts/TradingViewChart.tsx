'use client';

import React, { useEffect, useRef } from 'react';
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

  useEffect(() => {
    if (!chartContainerRef.current) return;

    const container = chartContainerRef.current;

    const chart = createChart(container, {
      width: container.clientWidth || 800,
      height: container.clientHeight || 400,
      layout: {
        background: { type: ColorType.Solid, color: '#090d16' },
        textColor: '#94a3b8',
      },
      grid: {
        vertLines: { color: '#1e293b' },
        horzLines: { color: '#1e293b' },
      },
      crosshair: { mode: 1 },
      handleScroll: {
        mouseWheel: true,
        pressedMouseMove: true,
        horzTouchDrag: true,
        vertTouchDrag: false, // Disable vertical drag collapsing
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
          bottom: 0.2,
        },
      },
      timeScale: {
        borderColor: '#334155',
        timeVisible: true,
        secondsVisible: true,
        rightOffset: 5,
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

    // Use ResizeObserver for accurate container dimensions
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

  useEffect(() => {
    if (!candlestickSeriesRef.current || !volumeSeriesRef.current) return;

    const candleData: CandlestickData[] = historicalCandles.map((c) => ({
      time: c.time as any,
      open: c.open,
      high: c.high,
      low: c.low,
      close: c.close,
    }));

    const volumeData = historicalCandles.map((c) => ({
      time: c.time as any,
      value: c.volume,
      color: c.close >= c.open ? 'rgba(16, 185, 129, 0.4)' : 'rgba(239, 68, 68, 0.4)',
    }));

    candlestickSeriesRef.current.setData(candleData);
    volumeSeriesRef.current.setData(volumeData);

    if (historicalCandles.length > 0 && chartRef.current) {
      chartRef.current.timeScale().scrollToRealTime();
    }
  }, [historicalCandles, selectedSymbol]);

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

  return (
    <div className="relative w-full h-full min-h-[440px] bg-[#090d16] rounded-xl border border-slate-800 p-2 flex flex-col shadow-xl overflow-hidden">
      <div className="flex flex-wrap items-center justify-between px-3 py-2 border-b border-slate-800 mb-2 gap-2 flex-shrink-0">
        <div className="flex items-center space-x-3">
          <span className="text-lg font-bold text-slate-100">{selectedSymbol}</span>
          <span className="text-xs px-2 py-0.5 rounded bg-emerald-500/10 text-emerald-400 border border-emerald-500/20 font-mono">
            LIVE TICK FEED
          </span>
        </div>
        {latestTick && (
          <div className="flex items-center space-x-4 font-mono text-xs">
            <span className="text-slate-400">O: <strong className="text-slate-200">${latestTick.open.toFixed(2)}</strong></span>
            <span className="text-slate-400">H: <strong className="text-emerald-400">${latestTick.high.toFixed(2)}</strong></span>
            <span className="text-slate-400">L: <strong className="text-rose-400">${latestTick.low.toFixed(2)}</strong></span>
            <span className="text-slate-400">C: <strong className="text-slate-100">${latestTick.close.toFixed(2)}</strong></span>
          </div>
        )}
      </div>
      <div ref={chartContainerRef} className="w-full flex-1 relative min-h-[380px] overflow-hidden" />
    </div>
  );
};
