"""Tests for SDK client endpoint methods — mocked HTTP responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from sdk.client import ModelionnClient
from sdk.errors import NotFoundError, ServerError


# ── Helpers ──────────────────────────────────────────────────

def _mock_response(
    status_code: int = 200,
    json_data: dict | None = None,
    headers: dict | None = None,
) -> MagicMock:
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = json_data or {}
    resp.text = json.dumps(json_data) if json_data else ""
    resp.headers = headers or {}
    return resp


def _client_with_mock(mock_resp, **kwargs):
    """Return a ModelionnClient whose HTTP layer returns mock_resp."""
    mock_http = MagicMock()
    if isinstance(mock_resp, list):
        mock_http.request.side_effect = mock_resp
    else:
        mock_http.request.return_value = mock_resp
    mock_http.is_closed = False
    return ModelionnClient(max_retries=0, **kwargs), mock_http


# ── list_circuits ────────────────────────────────────────────

class TestListCircuits:
    def test_basic(self):
        data = {"items": [{"id": 1, "name": "c1"}], "total": 1, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_circuits()
        assert result["total"] == 1
        assert result["items"][0]["name"] == "c1"

    def test_with_filters(self):
        data = {"items": [], "total": 0, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            c.list_circuits(proof_type="groth16", circuit_type="evm", page=2, page_size=10)
        call_kwargs = mock_http.request.call_args
        params = call_kwargs.kwargs.get("params") or call_kwargs[1].get("params", {})
        assert params["proof_type"] == "groth16"
        assert params["circuit_type"] == "evm"
        assert params["page"] == 2


# ── get_circuit ──────────────────────────────────────────────

class TestGetCircuit:
    def test_success(self):
        data = {"id": 42, "name": "my-circuit"}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.get_circuit(42)
        assert result["id"] == 42
        mock_http.request.assert_called_once()
        url_arg = mock_http.request.call_args[0][1]
        assert "/circuits/42" in url_arg

    def test_not_found(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=404, json_data={"detail": "not found"})
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            with pytest.raises(NotFoundError):
                c.get_circuit(999)


# ── upload_circuit ───────────────────────────────────────────

class TestUploadCircuit:
    def test_success(self):
        data = {"id": 1, "name": "uploaded", "circuit_hash": "abc123"}
        c, mock_http = _client_with_mock(
            _mock_response(status_code=200, json_data=data),
            hotkey="5FTestKey",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.upload_circuit(
                name="uploaded",
                version="1.0",
                proof_type="groth16",
                num_constraints=1000,
                data_cid="QmTest",
            )
        assert result["name"] == "uploaded"
        call_kwargs = mock_http.request.call_args
        # Should send auth headers
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert "x-hotkey" in headers

    def test_sends_json_body(self):
        c, mock_http = _client_with_mock(
            _mock_response(json_data={"id": 1}),
            hotkey="5FK",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            c.upload_circuit(
                name="test",
                version="2.0",
                proof_type="plonk",
                num_constraints=500,
                data_cid="QmData",
                proving_key_cid="QmPK",
                verification_key_cid="QmVK",
            )
        call_kwargs = mock_http.request.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        assert body["name"] == "test"
        assert body["proof_type"] == "plonk"
        assert body["num_constraints"] == 500


# ── request_proof ────────────────────────────────────────────

class TestRequestProof:
    def test_success(self):
        data = {"task_id": "abc123", "status": "queued", "circuit_id": 1}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data),
            hotkey="5FReq",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.request_proof(circuit_id=1, witness_cid="QmW")
        assert result["task_id"] == "abc123"
        assert result["status"] == "queued"

    def test_sends_auth_headers(self):
        c, mock_http = _client_with_mock(
            _mock_response(json_data={"task_id": "x"}),
            hotkey="5FAuth",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            c.request_proof(circuit_id=1, witness_cid="QmW")
        call_kwargs = mock_http.request.call_args
        headers = call_kwargs.kwargs.get("headers") or call_kwargs[1].get("headers", {})
        assert headers["x-hotkey"] == "5FAuth"


# ── get_proof_job ────────────────────────────────────────────

class TestGetProofJob:
    def test_success(self):
        data = {"task_id": "job1", "status": "proving"}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.get_proof_job("job1")
        assert result["status"] == "proving"

    def test_not_found(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=404, json_data={"detail": "not found"})
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            with pytest.raises(NotFoundError):
                c.get_proof_job("missing")


# ── list_proof_jobs ──────────────────────────────────────────

class TestListProofJobs:
    def test_basic(self):
        data = {"items": [], "total": 0, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_proof_jobs()
        assert result["total"] == 0

    def test_with_status_filter(self):
        data = {"items": [{"task_id": "a"}], "total": 1, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            c.list_proof_jobs(status="queued")
        params = mock_http.request.call_args.kwargs.get("params") or mock_http.request.call_args[1].get("params", {})
        assert params["status"] == "queued"


# ── verify_proof ─────────────────────────────────────────────

class TestVerifyProof:
    def test_success(self):
        data = {"valid": True, "proof_id": 1, "circuit_id": 2, "proof_system": "groth16"}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data),
            hotkey="5FV",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.verify_proof(proof_id=1, verification_key_cid="QmVK")
        assert result["valid"] is True


# ── list_provers ─────────────────────────────────────────────

class TestListProvers:
    def test_basic(self):
        data = {"items": [{"hotkey": "5FM1"}], "total": 1, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_provers()
        assert result["total"] == 1

    def test_online_only(self):
        data = {"items": [], "total": 0, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            c.list_provers(online_only=True)
        params = mock_http.request.call_args.kwargs.get("params") or mock_http.request.call_args[1].get("params", {})
        assert params["online_only"] == "true"


# ── get_network_stats ────────────────────────────────────────

class TestNetworkStats:
    def test_success(self):
        data = {"total_provers": 10, "online_provers": 8, "total_gpus": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.get_network_stats()
        assert result["total_provers"] == 10
        assert result["online_provers"] == 8

    def test_server_error(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=500, json_data={"detail": "boom"})
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            with pytest.raises(ServerError):
                c.get_network_stats()
