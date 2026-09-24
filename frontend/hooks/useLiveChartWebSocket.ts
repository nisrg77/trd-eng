import { useEffect, useRef } from 'react';
import { useTradingStore } from '@/store/useTradingStore';

export const useLiveChartWebSocket = (symbol: string, timeframe: string = '5s') => {
  const wsRef = useRef<WebSocket | null>(null);
  const isMountedRef = useRef<boolean>(true);

  const getWsUrl = () => {
    if (process.env.NEXT_PUBLIC_WS_URL) {
      const base = process.env.NEXT_PUBLIC_WS_URL.replace(/\/ws\/trading.*$/, '');
      return `${base}/ws/charts`;
    }
    if (typeof window !== 'undefined') {
      const isHttps = window.location.protocol === 'https:';
      const wsProtocol = isHttps ? 'wss' : 'ws';
      const host = window.location.hostname;
      if (host.includes('vercel.app')) {
        const awsIp = process.env.NEXT_PUBLIC_BACKEND_IP || '';
        if (awsIp) return `${wsProtocol}://${awsIp}:8000/ws/charts`;
      }
      return `${wsProtocol}://${host}:8000/ws/charts`;
    }
    return 'ws://localhost:8000/ws/charts';
  };

  useEffect(() => {
    isMountedRef.current = true;
    let reconnectTimeout: NodeJS.Timeout;
    let pingInterval: NodeJS.Timeout;
    const url = getWsUrl();

    // Browser check: prevent mixed-content websocket blocking on HTTPS
    const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
    if (isHttps && url.startsWith('ws:')) {
      return;
    }

    const connect = () => {
      try {
        const ws = new WebSocket(`${url}?symbol=${encodeURIComponent(symbol)}&timeframe=${encodeURIComponent(timeframe)}`);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMountedRef.current) return;
          // Send periodic keep-alive ping
          pingInterval = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ action: 'ping' }));
            }
          }, 15000);
        };

        ws.onmessage = (event) => {
          if (!isMountedRef.current) return;
          try {
            const data = JSON.parse(event.data);
            const payload = data.payload ?? data.data;
            if (!payload) return;

            switch (data.type) {
              case 'HISTORICAL_CANDLES': {
                const candles = Array.isArray(payload) ? payload : (payload.candles ?? []);
                if (candles && candles.length > 0) {
                  useTradingStore.getState().setHistoricalCandles(candles);
                  const lastCandle = candles[candles.length - 1];
                  if (lastCandle) {
                    useTradingStore.getState().updateTick(lastCandle);
                  }
                }
                break;
              }
              case 'TICK':
              case 'CHART_TICK': {
                useTradingStore.getState().updateTick(payload);
                break;
              }
              case 'PONG':
                break;
              default:
                break;
            }
          } catch (err) {
            console.error('[LiveChartWS] Parse error:', err);
          }
        };

        ws.onerror = () => {
          // Handled by onclose
        };

        ws.onclose = () => {
          if (pingInterval) clearInterval(pingInterval);
          if (isMountedRef.current) {
            reconnectTimeout = setTimeout(connect, 3000);
          }
        };
      } catch (err) {
        if (isMountedRef.current) {
          reconnectTimeout = setTimeout(connect, 3000);
        }
      }
    };

    connect();

    return () => {
      isMountedRef.current = false;
      clearTimeout(reconnectTimeout);
      if (pingInterval) clearInterval(pingInterval);
      if (wsRef.current) {
        wsRef.current.close();
        wsRef.current = null;
      }
    };
  }, [symbol, timeframe]);

  return { socket: wsRef.current };
};
