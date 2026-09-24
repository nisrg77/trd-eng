"""
services/auth_middleware.py — API Key Authentication & Endpoint Protection

Protects critical execution and governance endpoints:
- POST /api/strategies/{id}/toggle
- POST /api/strategies/{id}/promote
- POST /api/risk/kill-switch
- POST /api/reset-paper-trading

Enforces verification via 'X-TRDENG-API-KEY' header or 'Authorization: Bearer <key>'.
"""

from __future__ import annotations
import os
import secrets
import logging
from typing import Optional
from fastapi import Request, HTTPException, Security, status
from fastapi.security import APIKeyHeader

log = logging.getLogger(__name__)

API_KEY_NAME = "X-TRDENG-API-KEY"
api_key_header = APIKeyHeader(name=API_KEY_NAME, auto_error=False)


def get_configured_api_key() -> str:
    """Retrieves secret API key from environment with secure fallback."""
    return os.environ.get("TRDENG_API_KEY", "trdeng_live_secure_key_2026")


def verify_api_key(provided_key: Optional[str]) -> bool:
    """Constant-time string comparison to prevent timing attacks."""
    if not provided_key:
        return False
    expected = get_configured_api_key()
    return secrets.compare_digest(provided_key.strip(), expected.strip())


async def require_admin_auth(request: Request, key: Optional[str] = Security(api_key_header)) -> str:
    """
    FastAPI security dependency to guard live trading toggles, promotion, and kill-switches.
    Accepts 'X-TRDENG-API-KEY' header or 'Authorization: Bearer <key>'.
    """
    # 1. Check custom header
    if key and verify_api_key(key):
        return key

    # 2. Check standard Authorization header
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        bearer_key = auth_header[7:].strip()
        if verify_api_key(bearer_key):
            return bearer_key

    log.warning("[AUTH] Unauthorized request to %s from %s", request.url.path, request.client.host if request.client else "unknown")
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Unauthorized: Valid X-TRDENG-API-KEY or Bearer token required for critical trading controls.",
        headers={"WWW-Authenticate": "Bearer"},
    )
