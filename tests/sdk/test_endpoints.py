"""Tests for SDK client endpoint methods — mocked HTTP responses."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from sdk.client import ZKMLClient
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
    """Return a ZKMLClient whose HTTP layer returns mock_resp."""
    # Auto-provide a dummy sign_fn when hotkey is given (auth requires it)
    if "hotkey" in kwargs and "sign_fn" not in kwargs:
        kwargs["sign_fn"] = lambda msg: "deadbeef"
    mock_http = MagicMock()
    if isinstance(mock_resp, list):
        mock_http.request.side_effect = mock_resp
    else:
        mock_http.request.return_value = mock_resp
    mock_http.is_closed = False
    return ZKMLClient(max_retries=0, **kwargs), mock_http


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


# ── get_prover ───────────────────────────────────────────────

class TestGetProver:
    def test_success(self):
        data = {"hotkey": "5FM1", "gpu_name": "RTX 4090", "online": True}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.get_prover("5FM1")
        assert result["hotkey"] == "5FM1"
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/provers/5FM1")

    def test_not_found(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=404, json_data={"detail": "not found"})
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            with pytest.raises(NotFoundError):
                c.get_prover("5FGhost")


# ── register_prover ──────────────────────────────────────────

class TestRegisterProver:
    def test_success(self):
        data = {"hotkey": "5FM1", "gpu_backend": "cuda", "online": True}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FM1",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.register_prover(gpu_backend="cuda", gpu_name="RTX 4090")
        assert result["hotkey"] == "5FM1"
        call_kwargs = mock_http.request.call_args.kwargs
        assert call_kwargs["json"]["gpu_backend"] == "cuda"


# ── ping_prover ──────────────────────────────────────────────

class TestPingProver:
    def test_success(self):
        data = {"status": "ok"}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FM1",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.ping_prover(vram_available_bytes=1024)
        assert result["status"] == "ok"
        params = mock_http.request.call_args.kwargs.get("params", {})
        assert params["vram_available_bytes"] == 1024


# ── get_proof ────────────────────────────────────────────────

class TestGetProof:
    def test_success(self):
        data = {"id": 42, "proof_hash": "abc123", "verified": False}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.get_proof(42)
        assert result["id"] == 42
        url = mock_http.request.call_args[0][1]
        assert url.endswith("/proofs/42")

    def test_not_found(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=404, json_data={"detail": "not found"})
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            with pytest.raises(NotFoundError):
                c.get_proof(999)


# ── list_proofs ──────────────────────────────────────────────

class TestListProofs:
    def test_basic(self):
        data = {"items": [], "total": 0, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_proofs()
        assert result["total"] == 0

    def test_with_filters(self):
        data = {"items": [{"id": 1}], "total": 1, "page": 1, "page_size": 10}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            c.list_proofs(circuit_id=5, verified=True, page_size=10)
        params = mock_http.request.call_args.kwargs.get("params", {})
        assert params["circuit_id"] == 5
        assert params["verified"] == "true"


# ── get_job_partitions ───────────────────────────────────────

class TestGetJobPartitions:
    def test_success(self):
        data = [{"partition_index": 0, "status": "completed"}, {"partition_index": 1, "status": "proving"}]
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.get_job_partitions("abc123")
        assert len(result) == 2
        url = mock_http.request.call_args[0][1]
        assert "/proofs/jobs/abc123/partitions" in url


# ── list_my_orgs ─────────────────────────────────────────────

class TestListMyOrgs:
    def test_success(self):
        data = [{"id": 1, "slug": "my-org", "name": "My Org"}]
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FUser",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_my_orgs()
        assert len(result) == 1
        assert result[0]["slug"] == "my-org"


# ── get_org ──────────────────────────────────────────────────

class TestGetOrg:
    def test_success(self):
        data = {"id": 1, "slug": "test-org", "name": "Test Org"}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.get_org("test-org")
        assert result["slug"] == "test-org"

    def test_not_found(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=404, json_data={"detail": "not found"})
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            with pytest.raises(NotFoundError):
                c.get_org("nonexistent")


# ── create_org ───────────────────────────────────────────────

class TestCreateOrg:
    def test_success(self):
        data = {"id": 1, "slug": "new-org", "name": "New Org"}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FCreator",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.create_org(name="New Org", slug="new-org")
        assert result["slug"] == "new-org"
        call_kwargs = mock_http.request.call_args
        body = call_kwargs.kwargs.get("json") or call_kwargs[1].get("json", {})
        assert body["name"] == "New Org"
        assert body["slug"] == "new-org"


# ── list_members ─────────────────────────────────────────────

class TestListMembers:
    def test_success(self):
        data = {"items": [{"hotkey": "5FM1", "role": "admin"}], "total": 1, "page": 1, "page_size": 20}
        c, mock_http = _client_with_mock(_mock_response(json_data=data))
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_members("my-org")
        assert result["total"] == 1
        url = mock_http.request.call_args[0][1]
        assert "/orgs/my-org/members" in url


# ── add_member ───────────────────────────────────────────────

class TestAddMember:
    def test_success(self):
        data = {"hotkey": "5FNew", "role": "editor"}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FAdmin",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.add_member("my-org", hotkey="5FNew", role="editor")
        assert result["role"] == "editor"


# ── update_member_role ───────────────────────────────────────

class TestUpdateMemberRole:
    def test_success(self):
        data = {"hotkey": "5FM1", "role": "admin"}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FAdmin",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.update_member_role("my-org", "5FM1", role="admin")
        assert result["role"] == "admin"
        url = mock_http.request.call_args[0][1]
        assert "/orgs/my-org/members/5FM1" in url


# ── remove_member ────────────────────────────────────────────

class TestRemoveMember:
    def test_success(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=204), hotkey="5FAdmin",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            c.remove_member("my-org", "5FM1")
        assert mock_http.request.call_args[0][0] == "DELETE"


# ── create_api_key ───────────────────────────────────────────

class TestCreateApiKey:
    def test_success(self):
        data = {"id": 1, "key": "mnn_abc", "label": "ci", "daily_limit": 500}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FUser",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.create_api_key(label="ci", daily_limit=500)
        assert result["key"] == "mnn_abc"
        body = mock_http.request.call_args.kwargs.get("json", {})
        assert body["label"] == "ci"
        assert body["daily_limit"] == 500


# ── list_api_keys ────────────────────────────────────────────

class TestListApiKeys:
    def test_success(self):
        data = [{"id": 1, "label": "a"}, {"id": 2, "label": "b"}]
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FUser",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_api_keys()
        assert len(result) == 2


# ── revoke_api_key ───────────────────────────────────────────

class TestRevokeApiKey:
    def test_success(self):
        c, mock_http = _client_with_mock(
            _mock_response(status_code=204), hotkey="5FUser",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            c.revoke_api_key(42)
        url = mock_http.request.call_args[0][1]
        assert "/api-keys/42" in url


# ── list_audit_logs ──────────────────────────────────────────

class TestListAuditLogs:
    def test_basic(self):
        data = {"items": [{"id": 1, "action": "org.created"}], "total": 1, "page": 1, "page_size": 50}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FAudit",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.list_audit_logs()
        assert result["total"] == 1
        # Should send auth headers
        headers = mock_http.request.call_args.kwargs.get("headers", {})
        assert "x-hotkey" in headers

    def test_with_filters(self):
        data = {"items": [], "total": 0, "page": 1, "page_size": 50}
        c, mock_http = _client_with_mock(
            _mock_response(json_data=data), hotkey="5FA",
        )
        with patch.object(c, "_get_http", return_value=mock_http):
            c.list_audit_logs(action="org.created", resource_type="org", actor_hotkey="5FM")
        params = mock_http.request.call_args.kwargs.get("params", {})
        assert params["action"] == "org.created"
        assert params["resource_type"] == "org"
        assert params["actor_hotkey"] == "5FM"


# ── export_audit_csv ─────────────────────────────────────────

class TestExportAuditCSV:
    def test_success(self):
        csv_bytes = b"id,action\n1,org.created\n"
        c, mock_http = _client_with_mock(
            _mock_response(status_code=200, json_data=None, headers={"content-type": "text/csv"}),
            hotkey="5FA",
        )
        mock_http.request.return_value.content = csv_bytes
        with patch.object(c, "_get_http", return_value=mock_http):
            result = c.export_audit_csv(action="org.created", limit=100)
        assert result == csv_bytes
        params = mock_http.request.call_args.kwargs.get("params", {})
        assert params["action"] == "org.created"
        assert params["limit"] == 100
