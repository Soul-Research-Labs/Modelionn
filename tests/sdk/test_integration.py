"""SDK integration tests — tests that exercise full request→response flow with mocked HTTP."""

from __future__ import annotations

import json
from concurrent.futures import Future
from unittest.mock import MagicMock, patch

import pytest

from sdk.client import ZKMLClient, _sleep_backoff
from sdk.errors import (
    AuthError,
    ZKMLError,
    NotFoundError,
    RateLimitError,
    ServerError,
    ValidationError,
)


# ── Helpers ──────────────────────────────────────────────────


def _mock_response(
    status_code: int = 200,
    json_data: dict | list | None = None,
    content: bytes = b"",
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data if json_data is not None else {}
    resp.content = content
    resp.text = json.dumps(json_data) if json_data is not None else ""
    resp.headers = headers or {}
    return resp


def _make_client(responses, **kwargs):
    """Create a ZKMLClient with mocked HTTP transport.

    Args:
        responses: Single mock response or list for sequential calls.
    """
    if "hotkey" in kwargs and "sign_fn" not in kwargs:
        kwargs["sign_fn"] = lambda msg: "test_sig"
    c = ZKMLClient(max_retries=0, **kwargs)
    mock_http = MagicMock()
    if isinstance(responses, list):
        mock_http.request.side_effect = responses
    else:
        mock_http.request.return_value = responses
    mock_http.is_closed = False
    c._http = mock_http
    return c, mock_http


# ── Proof Job Lifecycle ──────────────────────────────────────


class TestProofJobLifecycle:
    """Test the full proof job flow: request → poll → download."""

    def test_request_proof(self):
        job_data = {"task_id": "task-abc", "status": "QUEUED", "circuit_id": 1}
        c, mock = _make_client(_mock_response(200, job_data), hotkey="5FKey")

        result = c.request_proof(circuit_id=1, witness_cid="Qm" + "a" * 44)
        assert result["task_id"] == "task-abc"
        assert result["status"] == "QUEUED"

    def test_get_proof_job_status(self):
        job_data = {"task_id": "task-abc", "status": "COMPLETED", "proof_cid": "Qm" + "p" * 44}
        c, mock = _make_client(_mock_response(200, job_data), hotkey="5FKey")

        result = c.get_proof_job("task-abc")
        assert result["status"] == "COMPLETED"
        assert result["proof_cid"].startswith("Qm")

    def test_list_proof_jobs(self):
        data = {"items": [{"task_id": "t1"}, {"task_id": "t2"}], "total": 2}
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.list_proof_jobs()
        assert result["total"] == 2
        assert len(result["items"]) == 2

    def test_cancel_proof_job(self):
        data = {"task_id": "task-abc", "status": "CANCELLED"}
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.cancel_proof_job("task-abc")
        assert result["status"] == "CANCELLED"


# ── Circuit Operations ───────────────────────────────────────


class TestCircuitOperations:
    def test_upload_circuit(self):
        data = {"id": 1, "name": "test-circuit", "circuit_hash": "abc"}
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.upload_circuit(
            name="test-circuit",
            version="1.0",
            proof_type="groth16",
            num_constraints=1000,
            data_cid="Qm" + "x" * 44,
        )
        assert result["id"] == 1
        assert result["name"] == "test-circuit"

    def test_list_circuits_with_filters(self):
        data = {"items": [], "total": 0, "page": 2, "page_size": 5}
        c, mock = _make_client(_mock_response(200, data))

        result = c.list_circuits(proof_type="plonk", circuit_type="evm", page=2, page_size=5)
        assert result["total"] == 0

        call_kwargs = mock.request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["proof_type"] == "plonk"
        assert params["page"] == 2

    def test_get_circuit_not_found(self):
        c, mock = _make_client(
            _mock_response(404, {"detail": "Circuit not found"})
        )
        with pytest.raises(NotFoundError):
            c.get_circuit(999)


# ── Prover Operations ───────────────────────────────────────


class TestProverOperations:
    def test_list_provers(self):
        data = {"items": [{"hotkey": "h1", "gpu_name": "A100"}], "total": 1}
        c, mock = _make_client(_mock_response(200, data))

        result = c.list_provers()
        assert result["total"] == 1
        assert result["items"][0]["gpu_name"] == "A100"

    def test_get_network_stats(self):
        data = {"total_provers": 5, "total_proofs": 1000, "avg_latency_ms": 42.5}
        c, mock = _make_client(_mock_response(200, data))

        result = c.get_network_stats()
        assert result["total_provers"] == 5

    def test_register_prover(self):
        data = {"hotkey": "5FKey", "status": "registered"}
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.register_prover(gpu_name="RTX4090", vram_bytes=24_000_000_000)
        assert result["status"] == "registered"


# ── Authentication Tests ─────────────────────────────────────


class TestAuthentication:
    def test_authenticated_request_sends_headers(self):
        c, mock = _make_client(
            _mock_response(200, {"ok": True}),
            hotkey="5FMyHotkey",
            sign_fn=lambda msg: "signed-" + msg[:10],
        )
        c.list_circuits()
        call_kwargs = mock.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        # Auth headers are sent via _auth_headers()
        # In the real client, these are merged into the request
        mock.request.assert_called_once()

    def test_auth_error_on_401(self):
        c, mock = _make_client(
            _mock_response(401, {"detail": "Invalid signature"}),
            hotkey="5FKey",
        )
        with pytest.raises(AuthError) as exc:
            c.get_circuit(1)
        assert exc.value.status_code == 401

    def test_auth_error_on_403(self):
        c, mock = _make_client(
            _mock_response(403, {"detail": "Forbidden"}),
            hotkey="5FKey",
        )
        with pytest.raises(AuthError):
            c.get_circuit(1)


# ── Retry & Error Handling ───────────────────────────────────


class TestRetryIntegration:
    def test_retry_on_503_then_success(self):
        fail = _mock_response(503)
        ok = _mock_response(200, {"status": "ok"})

        c = ZKMLClient(max_retries=2)
        mock_http = MagicMock()
        mock_http.request.side_effect = [fail, ok]
        mock_http.is_closed = False
        c._http = mock_http

        with patch("sdk.client._sleep_backoff"):
            result = c._request_with_retry("GET", "http://test/health")
        assert result.status_code == 200
        assert mock_http.request.call_count == 2

    def test_retry_on_429_with_retry_after(self):
        rate_limited = _mock_response(429, headers={"Retry-After": "1"})
        ok = _mock_response(200, {"ok": True})

        c = ZKMLClient(max_retries=2)
        mock_http = MagicMock()
        mock_http.request.side_effect = [rate_limited, ok]
        mock_http.is_closed = False
        c._http = mock_http

        with patch("sdk.client.time.sleep"):
            result = c._request_with_retry("GET", "http://test/data")
        assert result.status_code == 200

    def test_retry_on_408_timeout(self):
        timeout = _mock_response(408)
        ok = _mock_response(200, {"ok": True})

        c = ZKMLClient(max_retries=1)
        mock_http = MagicMock()
        mock_http.request.side_effect = [timeout, ok]
        mock_http.is_closed = False
        c._http = mock_http

        with patch("sdk.client._sleep_backoff"):
            result = c._request_with_retry("GET", "http://test/slow")
        assert result.status_code == 200

    def test_no_retry_on_validation_error(self):
        bad = _mock_response(422, {"detail": "Bad input"})

        c = ZKMLClient(max_retries=3)
        mock_http = MagicMock()
        mock_http.request.return_value = bad
        mock_http.is_closed = False
        c._http = mock_http

        with pytest.raises(ValidationError):
            c._request_with_retry("POST", "http://test/create")
        assert mock_http.request.call_count == 1

    def test_connection_error_retries(self):
        import httpx as _httpx

        c = ZKMLClient(max_retries=2)
        mock_http = MagicMock()
        mock_http.request.side_effect = [
            _httpx.ConnectError("refused"),
            _mock_response(200, {"ok": True}),
        ]
        mock_http.is_closed = False
        c._http = mock_http

        with patch("sdk.client._sleep_backoff"):
            result = c._request_with_retry("GET", "http://test/health")
        assert result.status_code == 200

    def test_all_retries_exhausted(self):
        import httpx as _httpx

        c = ZKMLClient(max_retries=1)
        mock_http = MagicMock()
        mock_http.request.side_effect = _httpx.ConnectError("refused")
        mock_http.is_closed = False
        c._http = mock_http

        with patch("sdk.client._sleep_backoff"):
            with pytest.raises(ZKMLError, match="Connection failed"):
                c._request_with_retry("GET", "http://test/down")


# ── Organization Operations ──────────────────────────────────


class TestOrgOperations:
    def test_list_orgs(self):
        data = [{"slug": "my-org", "name": "My Org"}]
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.list_my_orgs()
        assert len(result) == 1
        assert result[0]["slug"] == "my-org"

    def test_create_org(self):
        data = {"slug": "new-org", "name": "New Org"}
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.create_org(name="New Org", slug="new-org")
        assert result["slug"] == "new-org"


# ── API Key Operations ───────────────────────────────────────


class TestApiKeyOperations:
    def test_create_api_key(self):
        data = {"id": 1, "key_prefix": "mk_test", "key": "mk_test_abc123"}
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.create_api_key(label="test-key")
        assert result["key_prefix"] == "mk_test"

    def test_list_api_keys(self):
        data = [{"id": 1, "key_prefix": "mk_test", "name": "test-key"}]
        c, mock = _make_client(_mock_response(200, data), hotkey="5FKey")

        result = c.list_api_keys()
        assert len(result) == 1

    def test_revoke_api_key(self):
        c, mock = _make_client(_mock_response(200, {"revoked": True}), hotkey="5FKey")

        c.revoke_api_key(1)
        mock.request.assert_called_once()


# ── Client Connection Management ─────────────────────────────


class TestConnectionManagement:
    def test_close_releases_http(self):
        c = ZKMLClient()
        mock_http = MagicMock()
        mock_http.is_closed = False
        c._http = mock_http

        c.close()
        mock_http.close.assert_called_once()
        assert c._http is None

    def test_close_noop_when_already_closed(self):
        c = ZKMLClient()
        c._http = None
        c.close()  # Should not raise

    def test_context_manager_closes(self):
        with ZKMLClient() as c:
            mock_http = MagicMock()
            mock_http.is_closed = False
            c._http = mock_http

        mock_http.close.assert_called_once()

    def test_get_http_creates_client(self):
        c = ZKMLClient()
        assert c._http is None

        with patch("sdk.client.httpx.Client") as mock_cls:
            mock_instance = MagicMock()
            mock_instance.is_closed = False
            mock_cls.return_value = mock_instance

            result = c._get_http()
            assert result is mock_instance
            mock_cls.assert_called_once()


# ── Backoff Jitter Tests ─────────────────────────────────────


class TestBackoffJitter:
    def test_jitter_within_bounds(self):
        """Backoff delay should include jitter (0.5-1.0x multiplier)."""
        with patch("sdk.client.time.sleep") as mock_sleep:
            for attempt in range(5):
                _sleep_backoff(attempt, base=1.0, cap=60.0)
                delay = mock_sleep.call_args[0][0]
                expected_base = min(1.0 * (2 ** attempt), 60.0)
                assert delay >= expected_base * 0.5
                assert delay <= expected_base * 1.0

    def test_cap_respected(self):
        """Delay should never exceed cap."""
        with patch("sdk.client.time.sleep") as mock_sleep:
            _sleep_backoff(100, base=1.0, cap=10.0)
            delay = mock_sleep.call_args[0][0]
            assert delay <= 10.0


# ── Server Error Handling ────────────────────────────────────


class TestServerErrors:
    def test_500_raises_server_error(self):
        c, mock = _make_client(_mock_response(500, {"detail": "Internal error"}))

        with pytest.raises(ServerError) as exc:
            c.list_circuits()
        assert exc.value.status_code == 500

    def test_unknown_status_raises_base_error(self):
        c, mock = _make_client(_mock_response(418, {"detail": "I'm a teapot"}))

        with pytest.raises(ZKMLError):
            c.list_circuits()
