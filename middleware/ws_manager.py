"""
middleware/ws_manager.py — Unified WebSocket Connection Manager & Broadcast Hub

Centralized, thread-safe, and async-safe WebSocket connection registry and
event distribution router.
- Channels:
    * chart:{symbol}:{timeframe} -> Dedicated live chart candle & tick subscribers
    * trading                     -> Engine execution, portfolio, order & risk subscribers
- Features:
    * Safe connection lifecycle with dead-socket reaping
    * Thread-safe event dispatch bridge (publish_from_thread) from OMS / Orchestrator
    * Intelligent state deduplication (prevents redundant repeating socket spam)
    * Bidirectional ping/pong keep-alive handling
"""

from __future__ import annotations
import asyncio
import json
import logging
import time
import uuid
import hashlib
from typing import Dict, Set, Optional, Any, List, Union
from fastapi import WebSocket, WebSocketDisconnect
from middleware.ws_schema import WSEventType, format_ws_event

log = logging.getLogger(__name__)


class ConnectionManager:
    def __init__(self):
        self._connections: Dict[WebSocket, dict] = {} # websocket -> metadata
        self._channel_subscribers: Dict[str, Set[WebSocket]] = {} # channel -> set(ws)
        self._lock = asyncio.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._last_state_hashes: Dict[str, str] = {}
        self._last_state_timestamps: Dict[str, float] = {}

    def set_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Stores the running asyncio loop for thread-safe cross-thread dispatch."""
        self._loop = loop

    async def connect(
        self,
        websocket: WebSocket,
        client_type: str = "trading",
        initial_channels: Optional[List[str]] = None,
    ) -> str:
        """Accepts and registers a new WebSocket client."""
        client_id = f"client_{uuid.uuid4().hex[:8]}"
        channels = set(initial_channels or [])
        
        async with self._lock:
            self._connections[websocket] = {
                "client_id": client_id,
                "client_type": client_type,
                "channels": channels,
                "connected_at": time.time(),
                "last_active": time.time(),
            }
            for ch in channels:
                if ch not in self._channel_subscribers:
                    self._channel_subscribers[ch] = set()
                self._channel_subscribers[ch].add(websocket)

        log.info("[WS-Manager] Connected %s (type=%s, channels=%s, total=%d)",
                 client_id, client_type, list(channels), len(self._connections))
        return client_id

    async def disconnect(self, websocket: WebSocket) -> None:
        """Unregisters and cleans up a disconnected client."""
        async with self._lock:
            meta = self._connections.pop(websocket, None)
            if meta:
                client_id = meta.get("client_id", "unknown")
                for ch in meta.get("channels", set()):
                    if ch in self._channel_subscribers:
                        self._channel_subscribers[ch].discard(websocket)
                        if not self._channel_subscribers[ch]:
                            del self._channel_subscribers[ch]
                log.info("[WS-Manager] Disconnected %s (remaining=%d)", client_id, len(self._connections))

    async def subscribe(self, websocket: WebSocket, channel: str) -> None:
        """Subscribes a client to a named channel."""
        async with self._lock:
            if websocket in self._connections:
                self._connections[websocket]["channels"].add(channel)
                if channel not in self._channel_subscribers:
                    self._channel_subscribers[channel] = set()
                self._channel_subscribers[channel].add(websocket)
                log.debug("[WS-Manager] Subscribed to %s", channel)

    async def unsubscribe(self, websocket: WebSocket, channel: str) -> None:
        """Unsubscribes a client from a channel."""
        async with self._lock:
            if websocket in self._connections:
                self._connections[websocket]["channels"].discard(channel)
            if channel in self._channel_subscribers:
                self._channel_subscribers[channel].discard(websocket)
                if not self._channel_subscribers[channel]:
                    del self._channel_subscribers[channel]

    async def send_personal_message(self, websocket: WebSocket, message: dict) -> bool:
        """Sends a JSON message directly to a single socket."""
        try:
            await websocket.send_json(message)
            return True
        except Exception as e:
            log.debug("[WS-Manager] Error sending personal message: %s", e)
            await self.disconnect(websocket)
            return False

    async def broadcast_channel(self, channel: str, message: dict) -> int:
        """
        Broadcasts a message to all subscribers of a specific channel.
        Reaps dead sockets automatically.
        """
        targets: List[WebSocket] = []
        async with self._lock:
            if channel in self._channel_subscribers:
                targets = list(self._channel_subscribers[channel])

        if not targets:
            return 0

        dead_sockets: List[WebSocket] = []
        sent_count = 0

        for ws in targets:
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            await self.disconnect(ws)

        return sent_count

    async def broadcast_all(self, message: dict) -> int:
        """Broadcasts a message to every connected client across all channels."""
        targets: List[WebSocket] = []
        async with self._lock:
            targets = list(self._connections.keys())

        if not targets:
            return 0

        dead_sockets: List[WebSocket] = []
        sent_count = 0

        for ws in targets:
            try:
                await ws.send_json(message)
                sent_count += 1
            except Exception:
                dead_sockets.append(ws)

        for ws in dead_sockets:
            await self.disconnect(ws)

        return sent_count

    def publish_from_thread(
        self,
        event_type: Union[WSEventType, str],
        payload: Any,
        channel: Optional[str] = None
    ) -> None:
        """
        Thread-safe entry point for backend engine / OMS threads.
        Schedules broadcast into the running asyncio event loop without blocking caller.
        """
        if self._loop is None or not self._loop.is_running():
            return

        envelope = format_ws_event(event_type, payload, channel=channel)

        if channel:
            coro = self.broadcast_channel(channel, envelope)
        else:
            coro = self.broadcast_all(envelope)

        try:
            asyncio.run_coroutine_threadsafe(coro, self._loop)
        except Exception as e:
            log.debug("[WS-Manager] Failed to dispatch cross-thread event: %s", e)

    def is_state_dirty(self, state_key: str, data: Any, max_idle_seconds: float = 5.0) -> bool:
        """
        Checks whether data has changed compared to last broadcast,
        or if max_idle_seconds heartbeat interval has elapsed.
        Eliminates duplicate repeating frames!
        """
        try:
            serialized = json.dumps(data, sort_keys=True, default=str)
            cur_hash = hashlib.md5(serialized.encode("utf-8")).hexdigest()
        except Exception:
            return True

        now = time.time()
        last_hash = self._last_state_hashes.get(state_key)
        last_time = self._last_state_timestamps.get(state_key, 0.0)

        if cur_hash != last_hash or (now - last_time) >= max_idle_seconds:
            self._last_state_hashes[state_key] = cur_hash
            self._last_state_timestamps[state_key] = now
            return True

        return False

    @property
    def client_count(self) -> int:
        return len(self._connections)

    def channel_subscribers_count(self, channel: str) -> int:
        return len(self._channel_subscribers.get(channel, set()))


# Global Singleton WebSocket Manager
ws_manager = ConnectionManager()
