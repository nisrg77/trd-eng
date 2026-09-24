"""
tests/test_auth_middleware.py — Tests for API Authentication Middleware & Security
"""

import os
import pytest
from unittest.mock import MagicMock
from fastapi import HTTPException
from services.auth_middleware import verify_api_key, require_admin_auth, get_configured_api_key


def test_verify_api_key(monkeypatch):
    monkeypatch.setenv("TRDENG_API_KEY", "super_secret_test_key_123")
    
    assert verify_api_key("super_secret_test_key_123") is True
    assert verify_api_key("  super_secret_test_key_123  ") is True  # Strips whitespace
    assert verify_api_key("wrong_key") is False
    assert verify_api_key("") is False
    assert verify_api_key(None) is False


@pytest.mark.anyio
async def test_require_admin_auth_valid_header(monkeypatch):
    monkeypatch.setenv("TRDENG_API_KEY", "secret_key_abc")
    
    mock_request = MagicMock()
    mock_request.headers = {}
    mock_request.url.path = "/api/risk/kill-switch"
    mock_request.client.host = "127.0.0.1"

    # 1. Via X-TRDENG-API-KEY header argument
    key = await require_admin_auth(mock_request, key="secret_key_abc")
    assert key == "secret_key_abc"

    # 2. Via Authorization Bearer header
    mock_request.headers = {"Authorization": "Bearer secret_key_abc"}
    bearer_key = await require_admin_auth(mock_request, key=None)
    assert bearer_key == "secret_key_abc"


@pytest.mark.anyio
async def test_require_admin_auth_rejects_unauthorized(monkeypatch):
    monkeypatch.setenv("TRDENG_API_KEY", "secret_key_abc")

    mock_request = MagicMock()
    mock_request.headers = {"Authorization": "Bearer bad_key"}
    mock_request.url.path = "/api/strategies/toggle"
    mock_request.client.host = "127.0.0.1"

    # Invalid key raises 401
    with pytest.raises(HTTPException) as exc_info:
        await require_admin_auth(mock_request, key="invalid_key")
    assert exc_info.value.status_code == 401

    # Missing key raises 401
    mock_request.headers = {}
    with pytest.raises(HTTPException) as exc_info2:
        await require_admin_auth(mock_request, key=None)
    assert exc_info2.value.status_code == 401
