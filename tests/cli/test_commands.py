"""Tests for all CLI commands — uses mocked SDK client to avoid network calls."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from cli.main import app

runner = CliRunner()


# ── Helpers ──────────────────────────────────────────────────

def _mock_client(**methods) -> MagicMock:
    """Return a MagicMock for ZKMLClient with given method return values."""
    client = MagicMock()
    for name, retval in methods.items():
        getattr(client, name).return_value = retval
    return client


# ── info command ─────────────────────────────────────────────

class TestInfo:
    @patch("httpx.get")
    def test_info_table_output(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "network": "test"}
        mock_get.return_value = mock_resp

        result = runner.invoke(app, ["info", "--registry", "http://localhost:8000"])
        assert result.exit_code == 0
        assert "ok" in result.output

    @patch("httpx.get")
    def test_info_json_output(self, mock_get):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"status": "ok", "network": "test"}
        mock_get.return_value = mock_resp

        result = runner.invoke(app, ["info", "--json", "--registry", "http://localhost:8000"])
        assert result.exit_code == 0
        assert "ok" in result.output


# ── circuits command ─────────────────────────────────────────

class TestListCircuits:
    @patch("cli.main._client")
    def test_list_circuits_table(self, mock_client_fn):
        client = _mock_client(list_circuits={
            "items": [
                {"id": 1, "name": "test-circ", "proof_type": "groth16",
                 "circuit_type": "general", "num_constraints": 1000,
                 "proofs_generated": 5},
            ],
            "total": 1,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["circuits"])
        assert result.exit_code == 0
        assert "test-circ" in result.output

    @patch("cli.main._client")
    def test_list_circuits_json(self, mock_client_fn):
        data = {"items": [], "total": 0}
        client = _mock_client(list_circuits=data)
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["circuits", "--json"])
        assert result.exit_code == 0

    @patch("cli.main._client")
    def test_list_circuits_empty(self, mock_client_fn):
        client = _mock_client(list_circuits={"items": [], "total": 0})
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["circuits"])
        assert result.exit_code == 0


# ── upload-circuit command ───────────────────────────────────

class TestUploadCircuit:
    @patch("cli.main._client")
    def test_upload_success(self, mock_client_fn):
        client = _mock_client(upload_circuit={"id": 42, "circuit_hash": "abc123"})
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "upload-circuit",
            "--name", "my-circuit",
            "--constraints", "1000",
            "--cid", "QmTestCid123",
        ])
        assert result.exit_code == 0
        assert "42" in result.output

    @patch("cli.main._client")
    def test_upload_missing_required(self, mock_client_fn):
        """Missing --name should cause an error."""
        result = runner.invoke(app, [
            "upload-circuit",
            "--constraints", "1000",
            "--cid", "QmTestCid123",
        ])
        assert result.exit_code != 0


# ── prove command ────────────────────────────────────────────

class TestProve:
    @patch("cli.main._client")
    def test_prove_success(self, mock_client_fn):
        client = _mock_client(request_proof={
            "task_id": "task-abc-123",
            "status": "queued",
            "num_partitions": 4,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "prove", "1",
            "--witness", "QmWitnessCid",
        ])
        assert result.exit_code == 0
        assert "task-abc-123" in result.output

    @patch("cli.main._client")
    def test_prove_json_output(self, mock_client_fn):
        client = _mock_client(request_proof={
            "task_id": "task-abc-123", "status": "queued", "num_partitions": 4,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "prove", "1", "--witness", "QmWitness", "--json",
        ])
        assert result.exit_code == 0
        assert "task-abc-123" in result.output


# ── proof-status command ─────────────────────────────────────

class TestProofStatus:
    @patch("cli.main._client")
    def test_proof_status_in_progress(self, mock_client_fn):
        client = _mock_client(get_proof_job={
            "status": "proving", "partitions_completed": 2, "num_partitions": 4,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["proof-status", "task-abc"])
        assert result.exit_code == 0
        assert "proving" in result.output
        assert "2/4" in result.output

    @patch("cli.main._client")
    def test_proof_status_completed_with_time(self, mock_client_fn):
        client = _mock_client(get_proof_job={
            "status": "completed", "partitions_completed": 4,
            "num_partitions": 4, "actual_time_ms": 12500,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["proof-status", "task-abc"])
        assert result.exit_code == 0
        assert "completed" in result.output
        assert "12.5" in result.output

    @patch("cli.main._client")
    def test_proof_status_json(self, mock_client_fn):
        client = _mock_client(get_proof_job={"status": "completed"})
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["proof-status", "task-abc", "--json"])
        assert result.exit_code == 0


# ── proof-jobs command ───────────────────────────────────────

class TestProofJobs:
    @patch("cli.main._client")
    def test_list_proof_jobs(self, mock_client_fn):
        client = _mock_client(list_proof_jobs={
            "items": [
                {"task_id": "abcdefghijklmnopqr", "status": "completed",
                 "partitions_completed": 4, "num_partitions": 4,
                 "actual_time_ms": 5000},
            ],
            "total": 1,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["proof-jobs"])
        assert result.exit_code == 0
        assert "completed" in result.output

    @patch("cli.main._client")
    def test_list_proof_jobs_empty(self, mock_client_fn):
        client = _mock_client(list_proof_jobs={"items": [], "total": 0})
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["proof-jobs"])
        assert result.exit_code == 0


# ── verify-proof command ─────────────────────────────────────

class TestVerifyProof:
    @patch("cli.main._client")
    def test_verify_valid(self, mock_client_fn):
        client = _mock_client(verify_proof={"valid": True, "verification_time_ms": 50})
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "verify-proof", "1", "--vk-cid", "QmVerifKey",
        ])
        assert result.exit_code == 0
        assert "valid" in result.output.lower()

    @patch("cli.main._client")
    def test_verify_invalid(self, mock_client_fn):
        client = _mock_client(verify_proof={"valid": False})
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "verify-proof", "1", "--vk-cid", "QmVerifKey",
        ])
        assert result.exit_code == 1


# ── provers command ──────────────────────────────────────────

class TestProvers:
    @patch("cli.main._client")
    def test_list_provers(self, mock_client_fn):
        client = _mock_client(list_provers={
            "items": [
                {"hotkey": "5FTestHotkey123456", "gpu_name": "RTX 4090",
                 "gpu_backend": "cuda", "successful_proofs": 100,
                 "uptime_ratio": 0.95, "online": True},
            ],
            "total": 1,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["provers"])
        assert result.exit_code == 0
        assert "RTX 4090" in result.output

    @patch("cli.main._client")
    def test_list_provers_json(self, mock_client_fn):
        client = _mock_client(list_provers={"items": [], "total": 0})
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["provers", "--json"])
        assert result.exit_code == 0


# ── network-stats command ────────────────────────────────────

class TestNetworkStats:
    @patch("cli.main._client")
    def test_network_stats(self, mock_client_fn):
        client = _mock_client(get_network_stats={
            "online_provers": 10, "total_provers": 15,
            "total_proofs_generated": 5000, "total_circuits": 50,
            "active_jobs": 3, "avg_proof_time_ms": 8500,
            "total_gpu_vram_bytes": 320 * 1024 ** 3,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["network-stats"])
        assert result.exit_code == 0
        assert "10/15" in result.output
        assert "5,000" in result.output

    @patch("cli.main._client")
    def test_network_stats_json(self, mock_client_fn):
        client = _mock_client(get_network_stats={"online_provers": 0, "total_provers": 0})
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["network-stats", "--json"])
        assert result.exit_code == 0


# ── auth command ─────────────────────────────────────────────

class TestAuth:
    def test_auth_no_config(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".zkml.toml")
        monkeypatch.delenv("ZKML_HOTKEY", raising=False)
        monkeypatch.delenv("ZKML_REGISTRY", raising=False)

        result = runner.invoke(app, ["auth"])
        assert result.exit_code == 0
        assert "not found" in result.output or "not set" in result.output


# ── login command ────────────────────────────────────────────

class TestLogin:
    def test_login_saves_config(self, tmp_path, monkeypatch):
        config_path = tmp_path / ".zkml.toml"
        monkeypatch.setattr("cli.main._CONFIG_PATH", config_path)

        result = runner.invoke(app, [
            "login", "--hotkey", "5FTestHotkey123456789",
            "--registry", "http://test-registry:8000",
        ])
        assert result.exit_code == 0
        assert config_path.exists()
        content = config_path.read_text()
        assert "5FTestHotkey123456789" in content
        assert "http://test-registry:8000" in content

    def test_login_rejects_bad_url(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".zkml.toml")

        result = runner.invoke(app, ["login", "--registry", "not-a-url"])
        assert result.exit_code == 1

    def test_login_rejects_short_hotkey(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".zkml.toml")

        result = runner.invoke(app, ["login", "--hotkey", "abc"])
        assert result.exit_code == 1

    def test_login_no_args(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".zkml.toml")

        result = runner.invoke(app, ["login"])
        assert result.exit_code == 1

    def test_login_rejects_non_ss58_hotkey(self, tmp_path, monkeypatch):
        """Hotkeys with invalid characters (non-base58) should be rejected."""
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".zkml.toml")

        result = runner.invoke(app, [
            "login", "--hotkey", "0OIl0OIl0OIl0OIl0OIl0OIl0OIl0OIl0OIl0OIl0OIl0O",
        ])
        assert result.exit_code == 1


# ── org subcommands ──────────────────────────────────────────

class TestOrgList:
    @patch("cli.main._client")
    def test_org_list_table(self, mock_client_fn):
        client = _mock_client(list_my_orgs=[
            {"id": 1, "name": "Acme Labs", "slug": "acme-labs"},
            {"id": 2, "name": "ZK Corp", "slug": "zk-corp"},
        ])
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["org", "list"])
        assert result.exit_code == 0
        assert "Acme Labs" in result.output
        assert "zk-corp" in result.output

    @patch("cli.main._client")
    def test_org_list_json(self, mock_client_fn):
        client = _mock_client(list_my_orgs=[{"id": 1, "name": "Acme", "slug": "acme"}])
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["org", "list", "--json"])
        assert result.exit_code == 0

    @patch("cli.main._client")
    def test_org_list_empty(self, mock_client_fn):
        client = _mock_client(list_my_orgs=[])
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["org", "list"])
        assert result.exit_code == 0


class TestOrgCreate:
    @patch("cli.main._client")
    def test_org_create_success(self, mock_client_fn):
        client = _mock_client(create_org={"id": 10, "slug": "new-org"})
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "org", "create", "--name", "New Org", "--slug", "new-org",
        ])
        assert result.exit_code == 0
        assert "10" in result.output
        assert "new-org" in result.output


class TestOrgMembers:
    @patch("cli.main._client")
    def test_org_members_table(self, mock_client_fn):
        client = _mock_client(list_members={
            "items": [
                {"user_id": 1, "hotkey": "5FTestHotkey1234567890abcdef", "role": "admin"},
                {"user_id": 2, "hotkey": "5FMemberHotkey90abcdef123456", "role": "viewer"},
            ],
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["org", "members", "acme-labs"])
        assert result.exit_code == 0
        assert "admin" in result.output

    @patch("cli.main._client")
    def test_org_members_json(self, mock_client_fn):
        client = _mock_client(list_members={"items": []})
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["org", "members", "acme-labs", "--json"])
        assert result.exit_code == 0


class TestOrgAddMember:
    @patch("cli.main._client")
    def test_add_member_success(self, mock_client_fn):
        client = _mock_client(add_member={"role": "editor"})
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "org", "add-member", "acme-labs",
            "--hotkey-member", "5FNewMemberHotkeyAbcdef123456",
            "--role", "editor",
        ])
        assert result.exit_code == 0
        assert "editor" in result.output


class TestOrgRemoveMember:
    @patch("cli.main._client")
    def test_remove_member_success(self, mock_client_fn):
        client = _mock_client(remove_member=None)
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "org", "remove-member", "acme-labs",
            "--hotkey-member", "5FOldMemberHotkeyAbcdef123456",
        ])
        assert result.exit_code == 0
        assert "Removed" in result.output


# ── api-key subcommands ──────────────────────────────────────

class TestApiKeyCreate:
    @patch("cli.main._client")
    def test_create_api_key(self, mock_client_fn):
        client = _mock_client(create_api_key={
            "key": "mk_test_abc123def456", "label": "ci-key", "daily_limit": 500,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, [
            "api-key", "create", "--label", "ci-key", "--limit", "500",
        ])
        assert result.exit_code == 0
        assert "mk_test_abc123def456" in result.output
        assert "ci-key" in result.output

    @patch("cli.main._client")
    def test_create_api_key_defaults(self, mock_client_fn):
        client = _mock_client(create_api_key={
            "key": "mk_default_key", "label": "", "daily_limit": 1000,
        })
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["api-key", "create"])
        assert result.exit_code == 0


class TestApiKeyList:
    @patch("cli.main._client")
    def test_list_api_keys_table(self, mock_client_fn):
        client = _mock_client(list_api_keys=[
            {"id": 1, "label": "prod", "daily_limit": 5000,
             "requests_today": 42, "created_at": "2025-01-15T00:00:00Z"},
            {"id": 2, "label": "dev", "daily_limit": 100,
             "requests_today": 0, "created_at": "2025-06-01T00:00:00Z"},
        ])
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["api-key", "list"])
        assert result.exit_code == 0
        assert "prod" in result.output
        assert "5000" in result.output

    @patch("cli.main._client")
    def test_list_api_keys_json(self, mock_client_fn):
        client = _mock_client(list_api_keys=[])
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["api-key", "list", "--json"])
        assert result.exit_code == 0


class TestApiKeyRevoke:
    @patch("cli.main._client")
    def test_revoke_api_key(self, mock_client_fn):
        client = _mock_client(revoke_api_key=None)
        mock_client_fn.return_value = client

        result = runner.invoke(app, ["api-key", "revoke", "42"])
        assert result.exit_code == 0
        assert "42" in result.output
        assert "revoked" in result.output.lower()


# ── audit subcommands ────────────────────────────────────────

class TestAuditList:
    @patch("cli.main._default_registry", return_value="http://localhost:8000")
    @patch("sdk.client.ZKMLClient._request_with_retry")
    def test_audit_list_table(self, mock_req, _):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "items": [
                {"id": 1, "action": "circuit.uploaded", "actor_hotkey": "5FTestHotkey1234567890abcdef",
                 "resource_type": "circuit", "resource_id": "42",
                 "created_at": "2025-03-01T10:00:00Z"},
            ],
        }
        mock_req.return_value = mock_resp

        result = runner.invoke(app, ["audit", "list"])
        assert result.exit_code == 0
        assert "circuit.uploaded" in result.output

    @patch("cli.main._default_registry", return_value="http://localhost:8000")
    @patch("sdk.client.ZKMLClient._request_with_retry")
    def test_audit_list_json(self, mock_req, _):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": []}
        mock_req.return_value = mock_resp

        result = runner.invoke(app, ["audit", "list", "--json"])
        assert result.exit_code == 0

    @patch("cli.main._default_registry", return_value="http://localhost:8000")
    @patch("sdk.client.ZKMLClient._request_with_retry")
    def test_audit_list_with_filters(self, mock_req, _):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"items": []}
        mock_req.return_value = mock_resp

        result = runner.invoke(app, [
            "audit", "list", "--action", "proof.completed",
            "--resource-type", "proof", "--actor", "5FTestHotkey",
        ])
        assert result.exit_code == 0
        # Verify filters were passed as params
        _, kwargs = mock_req.call_args
        assert kwargs["params"]["action"] == "proof.completed"
