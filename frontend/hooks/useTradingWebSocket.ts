import { useEffect, useRef } from 'react';
import { useTradingStore } from '@/store/useTradingStore';

export const useTradingWebSocket = (url: string = 'ws://localhost:8000/ws/trading') => {
  const wsRef = useRef<WebSocket | null>(null);
  const {
    selectedSymbol,
    updateTick,
    updateOrderBook,
    updateAccount,
    addSignal,
    addExecution,
    addLog,
    setConnectionStatus,
  } = useTradingStore();

  useEffect(() => {
    let reconnectTimeout: NodeJS.Timeout;
    let isMounted = true;

    const connect = () => {
      try {
        setConnectionStatus('RECONNECTING');
        const ws = new WebSocket(`${url}?symbol=${selectedSymbol}`);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMounted) return;
          setConnectionStatus('CONNECTED');
          addLog({
            id: `ws_open_${Date.now()}`,
            timestamp: Date.now() / 1000,
            level: 'SUCCESS',
            message: `WebSocket connected to stream for ${selectedSymbol}`,
            source: 'ENGINE',
          });
        };

        ws.onmessage = (event) => {
          if (!isMounted) return;
          try {
            const data = JSON.parse(event.data);
            switch (data.type) {
              case 'TICK':
                updateTick(data.payload);
                break;
              case 'ORDER_BOOK':
                updateOrderBook(data.payload);
                break;
              case 'ACCOUNT_UPDATE':
                updateAccount(data.payload);
                break;
              case 'ML_SIGNAL':
                addSignal(data.payload);
                break;
              case 'EXECUTION':
                addExecution(data.payload);
                break;
              case 'LOG':
                addLog(data.payload);
                break;
              case 'QUOTA_UPDATE':
                useTradingStore.getState().updateQuotaState(data.payload);
                break;
              case 'SCREENER_UPDATE':
                useTradingStore.getState().updateScreenerTargets(data.payload);
                break;
            }
          } catch (err) {
            console.error('WebSocket frame parse error:', err);
          }
        };

        ws.onerror = () => {
          if (isMounted) setConnectionStatus('DISCONNECTED');
        };

        ws.onclose = () => {
          if (!isMounted) return;
          setConnectionStatus('DISCONNECTED');
          reconnectTimeout = setTimeout(connect, 3000);
        };
      } catch (e) {
        if (isMounted) {
          setConnectionStatus('DISCONNECTED');
          reconnectTimeout = setTimeout(connect, 3000);
        }
      }
    };

    connect();

    return () => {
      isMounted = false;
      clearTimeout(reconnectTimeout);
      if (wsRef.current) wsRef.current.close();
    };
  }, [selectedSymbol, url]);

  return { socket: wsRef.current };
};
