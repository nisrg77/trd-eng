"""
middleware/broker.py — [MB] Message Broker  (Redis Pub/Sub with in-process fallback)

Auto-detection logic:
  • If Redis is reachable at config.REDIS_HOST:REDIS_PORT  → use Redis Pub/Sub
  • Otherwise                                              → use an in-process
    queue backed by a thread-safe queue.Queue (same API, no external deps)

Public API:
  broker = Broker()
  broker.publish(channel, payload_dict)   # non-blocking
  for msg in broker.subscribe(channel):   # blocking generator
      handle(msg)
"""

from __future__ import annotations

import json
import logging
import queue
import threading
from typing import Generator

import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
import config

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# IN-PROCESS FALLBACK BROKER
# ─────────────────────────────────────────────────────────────────────────────

class _InProcessBroker:
    """
    Thread-safe in-process pub/sub using queue.Queue objects per channel.
    All subscriber queues on the same channel receive every published message.
    """

    def __init__(self) -> None:
        self._channels: dict[str, list[queue.Queue]] = {}
        self._lock = threading.Lock()
        log.warning(
            "Redis unavailable — using in-process queue broker (single-process only)"
        )

    def publish(self, channel: str, payload: dict) -> None:
        data = json.dumps(payload)
        with self._lock:
            subs = self._channels.get(channel, [])
        for q in subs:
            q.put(data)

    def subscribe(self, channel: str) -> Generator[dict, None, None]:
        q: queue.Queue = queue.Queue()
        with self._lock:
            self._channels.setdefault(channel, []).append(q)
        log.info("InProcessBroker: subscribed to '%s'", channel)
        try:
            while True:
                raw = q.get()
                yield json.loads(raw)
        finally:
            with self._lock:
                self._channels[channel].remove(q)


# ─────────────────────────────────────────────────────────────────────────────
# REDIS BROKER
# ─────────────────────────────────────────────────────────────────────────────

class _RedisBroker:
    """
    Redis Pub/Sub wrapper.
    Uses a connection pool for publish operations.
    """

    def __init__(self, client) -> None:
        self._client = client
        log.info(
            "RedisBroker connected to %s:%d",
            config.REDIS_HOST,
            config.REDIS_PORT,
        )

    def publish(self, channel: str, payload: dict) -> None:
        data = json.dumps(payload)
        self._client.publish(channel, data)

    def subscribe(self, channel: str) -> Generator[dict, None, None]:
        pubsub = self._client.pubsub()
        pubsub.subscribe(channel)
        log.info("RedisBroker: subscribed to '%s'", channel)
        for raw in pubsub.listen():
            if raw["type"] == "message":
                try:
                    yield json.loads(raw["data"])
                except json.JSONDecodeError as exc:
                    log.error("JSON decode error: %s", exc)


# ─────────────────────────────────────────────────────────────────────────────
# PUBLIC FACTORY — auto-detects Redis
# ─────────────────────────────────────────────────────────────────────────────

def _try_redis():
    """Attempt to connect to Redis; return client or None."""
    try:
        import redis
        client = redis.Redis(
            host=config.REDIS_HOST,
            port=config.REDIS_PORT,
            db=config.REDIS_DB,
            socket_connect_timeout=1,
            decode_responses=True,
        )
        client.ping()
        return client
    except Exception:
        return None


def Broker():
    """
    Factory function — returns either a _RedisBroker or _InProcessBroker
    depending on Redis availability.
    """
    client = _try_redis()
    if client is not None:
        return _RedisBroker(client)
    return _InProcessBroker()
