import { useEffect, useRef } from 'react';
import { useTradingStore } from '@/store/useTradingStore';

/** Normalize OMS exit records (sim_exit_*) into the OrderExecution shape */
function normalizeExecution(ex: any) {
  return {
    order_id:               ex.order_id  ?? ex.alpaca_order_id ?? `oms_${Date.now()}`,
    signal_id:              ex.signal_id ?? ex.order_id ?? '',
    instrument:             ex.instrument ?? ex.symbol ?? '',
    action:                 ex.action ?? (ex.qty > 0 ? 'BUY' : 'SELL'),
    order_type:             ex.order_type ?? (ex.reason ? 'MARKET' : 'LIMIT'),
    portfolio_allocation_pct: ex.portfolio_allocation_pct ?? ex.alloc_pct ?? 0,
    confidence:             ex.confidence ?? 0,
    timestamp_proposed:     ex.timestamp ?? ex.timestamp_proposed ?? (Date.now() / 1000),
    risk_state:             ex.risk_state ?? (ex.oms_state === 'SKIPPED_BY_RISK' ? 'REJECTED' : 'APPROVED'),
    checks_passed:          ex.checks_passed ?? [],
    failed_check:           ex.failed_check ?? ex.oms_detail ?? null,
    oms_state:              ex.oms_state ?? 'FILLED',
    oms_detail:             ex.oms_detail ?? ex.reason ?? null,
    notional_value:         ex.notional_value ?? ex.realized_pnl ?? null,
  };
}

import { getApiBaseUrl } from '@/lib/utils';

export const useTradingWebSocket = () => {
  // Dynamically get protocol (wss if https, ws if http) and host
  const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
  const wsProtocol = isHttps ? 'wss' : 'ws';
  const host = typeof window !== 'undefined' ? window.location.hostname : 'localhost';
  const defaultUrl = `${wsProtocol}://${host}:8000/ws/trading`;
  const url = process.env.NEXT_PUBLIC_WS_URL || defaultUrl;
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
    updateMicrostructure,
  } = useTradingStore();

  useEffect(() => {
    let reconnectTimeout: NodeJS.Timeout;
    let pollInterval: NodeJS.Timeout;
    let isMounted = true;

    // HTTP Polling fallback if WebSocket is disconnected
    const pollFallbackData = async () => {
      try {
        const baseUrl = getApiBaseUrl();
        const [posRes, healthRes] = await Promise.all([
          fetch(`${baseUrl}/api/positions`).catch(() => null),
          fetch(`${baseUrl}/api/engine-health`).catch(() => null),
        ]);

        if (posRes && posRes.ok) {
          const posData = await posRes.json();
          if (posData && posData.positions) {
            updateAccount({ positions: posData.positions });
          }
        }
        if (healthRes && healthRes.ok) {
          setConnectionStatus('CONNECTED');
        }
      } catch (e) {
        // Silent fallback catch
      }
    };

    const connect = () => {
      try {
        setConnectionStatus('RECONNECTING');
        const ws = new WebSocket(`${url}?symbol=${selectedSymbol}`);
        wsRef.current = ws;

        ws.onopen = () => {
          if (!isMounted) return;
          setConnectionStatus('CONNECTED');
          if (pollInterval) clearInterval(pollInterval);
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
              case 'HISTORICAL_CANDLES':
                useTradingStore.getState().setHistoricalCandles(data.payload);
                break;
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
                addExecution(normalizeExecution(data.payload));
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
              case 'MICROSTRUCTURE':
                useTradingStore.getState().updateMicrostructure(data.payload);
                break;
              case 'MARKET_SESSION':
                useTradingStore.getState().updateMarketSession(data.payload);
                break;
              case 'GOAL_UPDATE':
                useTradingStore.getState().updateGoalSummary(data.payload);
                break;
            }
          } catch (err) {
            console.error('WebSocket frame parse error:', err);
          }
        };

        ws.onerror = () => {
          if (isMounted) {
            setConnectionStatus('DISCONNECTED');
            pollFallbackData();
          }
        };

        ws.onclose = () => {
          if (!isMounted) return;
          setConnectionStatus('DISCONNECTED');
          pollFallbackData();
          if (!pollInterval) {
            pollInterval = setInterval(pollFallbackData, 3000);
          }
          reconnectTimeout = setTimeout(connect, 3000);
        };
      } catch (e) {
        if (isMounted) {
          setConnectionStatus('DISCONNECTED');
          pollFallbackData();
          if (!pollInterval) {
            pollInterval = setInterval(pollFallbackData, 3000);
          }
          reconnectTimeout = setTimeout(connect, 3000);
        }
      }
    };

    connect();

    return () => {
      isMounted = false;
      clearTimeout(reconnectTimeout);
      if (pollInterval) clearInterval(pollInterval);
      if (wsRef.current) wsRef.current.close();
    };
  }, [selectedSymbol, url]);

  return { socket: wsRef.current };
};
