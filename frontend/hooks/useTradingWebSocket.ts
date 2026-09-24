import { useEffect, useRef } from 'react';
import { useTradingStore } from '@/store/useTradingStore';

/** Normalize OMS exit records (sim_exit_*) into the OrderExecution shape */
function normalizeExecution(ex: any) {
  const qtyVal = ex.qty ?? ex.quantity ?? ex.size ?? 0;
  return {
    order_id:               ex.order_id  ?? ex.alpaca_order_id ?? `oms_${Date.now()}`,
    signal_id:              ex.signal_id ?? ex.order_id ?? '',
    instrument:             ex.instrument ?? ex.symbol ?? '',
    action:                 ex.action ?? (qtyVal > 0 ? 'BUY' : 'SELL'),
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
    qty:                    qtyVal,
    quantity:               Math.abs(qtyVal),
    price:                  ex.price ?? ex.entry_price ?? null,
    realized_pnl:           ex.realized_pnl ?? null,
  };
}

/** Standardize positions dictionary so symbol and qty are always reliably present */
export function normalizePositions(rawPositions: any): Record<string, any> {
  if (!rawPositions) return {};
  const normalized: Record<string, any> = {};
  if (Array.isArray(rawPositions)) {
    for (const pos of rawPositions) {
      const sym = pos.symbol ?? pos.instrument;
      if (!sym) continue;
      const rawSize = pos.size ?? pos.qty ?? 0;
      const isShort = String(pos.side).toLowerCase() === 'short' || pos.qty < 0;
      const qty = isShort ? -Math.abs(rawSize) : Math.abs(rawSize);
      normalized[sym] = {
        ...pos,
        symbol: sym,
        instrument: sym,
        qty: qty,
        size: Math.abs(qty),
        entry_price: pos.entry_price ?? pos.price ?? 0,
        current_price: pos.current_price ?? pos.mark_price ?? pos.entry_price ?? 0,
        unrealized_pl: pos.unrealized_pl ?? pos.unrealized_pnl ?? 0,
      };
    }
  } else if (typeof rawPositions === 'object') {
    for (const [key, pos] of Object.entries(rawPositions)) {
      if (!pos || typeof pos !== 'object') continue;
      const sym = (pos as any).symbol ?? (pos as any).instrument ?? key;
      const rawSize = (pos as any).size ?? (pos as any).qty ?? 0;
      const isShort = String((pos as any).side).toLowerCase() === 'short' || (pos as any).qty < 0;
      const qty = isShort ? -Math.abs(rawSize) : Math.abs(rawSize);
      normalized[sym] = {
        ...(pos as any),
        symbol: sym,
        instrument: sym,
        qty: qty,
        size: Math.abs(qty),
        entry_price: (pos as any).entry_price ?? (pos as any).price ?? 0,
        current_price: (pos as any).current_price ?? (pos as any).mark_price ?? (pos as any).entry_price ?? 0,
        unrealized_pl: (pos as any).unrealized_pl ?? (pos as any).unrealized_pnl ?? 0,
      };
    }
  }
  return normalized;
}

import { getApiBaseUrl } from '@/lib/utils';

export const useTradingWebSocket = () => {
  const getWsUrl = () => {
    if (process.env.NEXT_PUBLIC_WS_URL) {
      return process.env.NEXT_PUBLIC_WS_URL;
    }
    if (typeof window !== 'undefined') {
      const isHttps = window.location.protocol === 'https:';
      const wsProtocol = isHttps ? 'wss' : 'ws';
      const host = window.location.hostname;
      if (host.includes('vercel.app')) {
        const awsIp = process.env.NEXT_PUBLIC_BACKEND_IP || '';
        if (awsIp) return `${wsProtocol}://${awsIp}:8000/ws/trading`;
      }
      return `${wsProtocol}://${host}:8000/ws/trading`;
    }
    return 'ws://localhost:8000/ws/trading';
  };

  const url = getWsUrl();
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
        const [posRes, healthRes, klinesRes] = await Promise.all([
          fetch(`${baseUrl}/api/positions`).catch(() => null),
          fetch(`${baseUrl}/api/engine-health`).catch(() => null),
          fetch(`${baseUrl}/api/klines?symbol=${selectedSymbol}`).catch(() => null),
        ]);

        if (posRes && posRes.ok) {
          const posData = await posRes.json();
          if (posData && posData.positions) {
            updateAccount({ positions: normalizePositions(posData.positions) });
          }
        }
        if (klinesRes && klinesRes.ok) {
          const klinesData = await klinesRes.json();
          if (klinesData && klinesData.candles && klinesData.candles.length > 0) {
            useTradingStore.getState().setHistoricalCandles(klinesData.candles);
            const lastCandle = klinesData.candles[klinesData.candles.length - 1];
            if (lastCandle) updateTick(lastCandle);
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
        // Instantly fetch initial HTTP fallback data
        pollFallbackData();

        // If on HTTPS and no wss endpoint, browsers block ws:// with Mixed Content error.
        const isHttps = typeof window !== 'undefined' && window.location.protocol === 'https:';
        if (isHttps && url.startsWith('ws:')) {
          // Fall back gracefully to HTTPS HTTP polling without raising browser console blocks
          if (!pollInterval) {
            pollInterval = setInterval(pollFallbackData, 2000);
          }
          return;
        }

        const ws = new WebSocket(`${url}?symbol=${selectedSymbol}`);
        wsRef.current = ws;

        let pingTimer: NodeJS.Timeout;

        ws.onopen = () => {
          if (!isMounted) return;
          setConnectionStatus('CONNECTED');
          if (pollInterval) clearInterval(pollInterval);

          // Periodic keep-alive ping
          pingTimer = setInterval(() => {
            if (ws.readyState === WebSocket.OPEN) {
              ws.send(JSON.stringify({ action: 'ping' }));
            }
          }, 15000);

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
            const payload = data.payload ?? data.data;
            if (!payload && data.type !== 'PONG') return;

            switch (data.type) {
              case 'HISTORICAL_CANDLES': {
                const candles = Array.isArray(payload) ? payload : (payload.candles ?? []);
                if (candles && candles.length > 0) {
                  useTradingStore.getState().setHistoricalCandles(candles);
                }
                break;
              }
              case 'TICK':
              case 'CHART_TICK':
                updateTick(payload);
                break;

              case 'ORDER_BOOK':
                updateOrderBook(payload);
                break;
              case 'ACCOUNT_UPDATE':
                if (payload && payload.positions) {
                  payload.positions = normalizePositions(payload.positions);
                }
                updateAccount(payload);
                break;
              case 'POSITION_UPDATE': {
                const pos = payload;
                if (pos && (pos.symbol || pos.instrument)) {
                  const sym = pos.symbol ?? pos.instrument;
                  const curPositions = { ...useTradingStore.getState().account.positions };
                  if (String(pos.status).toLowerCase() === 'closed') {
                    delete curPositions[sym];
                  } else {
                    curPositions[sym] = pos;
                  }
                  updateAccount({ positions: normalizePositions(curPositions) });
                }
                break;
              }
              case 'ML_SIGNAL':
                addSignal(payload);
                break;
              case 'EXECUTION':
              case 'EXECUTION_LOG':
                addExecution(normalizeExecution(payload));
                break;
              case 'LOG':
                addLog(payload);
                break;
              case 'QUOTA_UPDATE':
                useTradingStore.getState().updateQuotaState(payload);
                break;
              case 'SCREENER_UPDATE':
                useTradingStore.getState().updateScreenerTargets(payload);
                break;
              case 'MICROSTRUCTURE':
                useTradingStore.getState().updateMicrostructure(payload);
                break;
              case 'MARKET_SESSION':
                useTradingStore.getState().updateMarketSession(payload);
                break;
              case 'GOAL_UPDATE':
                useTradingStore.getState().updateGoalSummary(payload);
                break;
              case 'ENGINE_HEALTH':
                if (payload && payload.status === 'healthy') {
                  setConnectionStatus('CONNECTED');
                }
                break;
              case 'PONG':
                break;
            }
          } catch (err) {
            console.error('WebSocket frame parse error:', err);
          }
        };

        ws.onerror = () => {
          if (pingTimer) clearInterval(pingTimer);
          if (isMounted) {
            setConnectionStatus('DISCONNECTED');
            pollFallbackData();
          }
        };

        ws.onclose = () => {
          if (pingTimer) clearInterval(pingTimer);
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
