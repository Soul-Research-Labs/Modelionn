"""Tests for the SDK client — initialization, auth, retry logic."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from sdk.client import ModelionnClient, _sleep_backoff
from sdk.errors import (
    AuthError,
    ModelionnError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
    raise_for_status,
)


# ── Helpers ──────────────────────────────────────────────────

def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    content: bytes = b"",
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.content = content
    resp.text = json.dumps(json_data) if json_data else ""
    resp.headers = headers or {}
    return resp


# ── Error hierarchy ──────────────────────────────────────────

class TestErrorHierarchy:
    def test_raise_for_status_200(self):
        raise_for_status(200)  # no exception

    def test_raise_for_status_401(self):
        with pytest.raises(AuthError) as exc:
            raise_for_status(401, "bad token")
        assert exc.value.status_code == 401

    def test_raise_for_status_403(self):
        with pytest.raises(AuthError):
            raise_for_status(403)

    def test_raise_for_status_404(self):
        with pytest.raises(NotFoundError):
            raise_for_status(404, "not found")

    def test_raise_for_status_422(self):
        with pytest.raises(ValidationError):
            raise_for_status(422, "invalid")

    def test_raise_for_status_429(self):
        with pytest.raises(RateLimitError):
            raise_for_status(429)

    def test_raise_for_status_500(self):
        with pytest.raises(ServerError):
            raise_for_status(500, "oops")

    def test_raise_for_status_unknown(self):
        with pytest.raises(ModelionnError):
            raise_for_status(418, "teapot")

    def test_all_inherit_from_base(self):
        for cls in (AuthError, NotFoundError, RateLimitError, ValidationError, ServerError):
            assert issubclass(cls, ModelionnError)


# ── Client initialization ────────────────────────────────────

class TestClientInit:
    def test_default_url(self):
        c = ModelionnClient()
        assert c._url == "http://localhost:8000"

    def test_custom_url_strips_slash(self):
        c = ModelionnClient("https://registry.example.com/")
        assert c._url == "https://registry.example.com"

    def test_context_manager(self):
        with ModelionnClient() as c:
            assert isinstance(c, ModelionnClient)

    def test_auth_headers_empty_without_hotkey(self):
        c = ModelionnClient()
        assert c._auth_headers() == {}

    def test_auth_headers_with_hotkey(self):
        c = ModelionnClient(hotkey="5FTestHotkey123")
        headers = c._auth_headers()
        assert headers["x-hotkey"] == "5FTestHotkey123"
        assert "x-nonce" in headers
        assert "x-signature" in headers

    def test_auth_headers_with_custom_signer(self):
        signer = MagicMock(return_value="custom_sig")
        c = ModelionnClient(hotkey="5FKey", sign_fn=signer)
        headers = c._auth_headers()
        assert headers["x-signature"] == "custom_sig"
        signer.assert_called_once()


# ── Retry logic ──────────────────────────────────────────────

class TestRetry:
    def test_backoff_exponential(self):
        with patch("sdk.client.time.sleep") as mock_sleep:
            _sleep_backoff(0, base=1.0, cap=15.0)
            mock_sleep.assert_called_with(1.0)
            _sleep_backoff(1, base=1.0, cap=15.0)
            mock_sleep.assert_called_with(2.0)
            _sleep_backoff(3, base=1.0, cap=15.0)
            mock_sleep.assert_called_with(8.0)

    def test_backoff_capped(self):
        with patch("sdk.client.time.sleep") as mock_sleep:
            _sleep_backoff(10, base=1.0, cap=15.0)
            mock_sleep.assert_called_with(15.0)

    def test_retry_on_503(self):
        fail_resp = _mock_response(503)
        ok_resp = _mock_response(200, {"status": "ok"})

        mock_client = MagicMock()
        mock_client.request.side_effect = [fail_resp, ok_resp]
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("sdk.client.httpx.Client", return_value=mock_client), \
             patch("sdk.client._sleep_backoff"):
            c = ModelionnClient(max_retries=3)
            resp = c._request_with_retry("GET", "http://test/health")
            assert resp.status_code == 200

    def test_no_retry_on_400(self):
        bad_resp = _mock_response(422, {"detail": "invalid"})

        mock_client = MagicMock()
        mock_client.request.return_value = bad_resp
        mock_client.__enter__ = MagicMock(return_value=mock_client)
        mock_client.__exit__ = MagicMock(return_value=False)

        with patch("sdk.client.httpx.Client", return_value=mock_client):
            c = ModelionnClient(max_retries=3)
            with pytest.raises(ValidationError):
                c._request_with_retry("GET", "http://test/bad")
            assert mock_client.request.call_count == 1
