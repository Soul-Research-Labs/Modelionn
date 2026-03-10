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
    """Return a MagicMock for ModelionnClient with given method return values."""
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
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".modelionn.toml")
        monkeypatch.delenv("MODELIONN_HOTKEY", raising=False)
        monkeypatch.delenv("MODELIONN_REGISTRY", raising=False)

        result = runner.invoke(app, ["auth"])
        assert result.exit_code == 0
        assert "not found" in result.output or "not set" in result.output


# ── login command ────────────────────────────────────────────

class TestLogin:
    def test_login_saves_config(self, tmp_path, monkeypatch):
        config_path = tmp_path / ".modelionn.toml"
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
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".modelionn.toml")

        result = runner.invoke(app, ["login", "--registry", "not-a-url"])
        assert result.exit_code == 1

    def test_login_rejects_short_hotkey(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".modelionn.toml")

        result = runner.invoke(app, ["login", "--hotkey", "abc"])
        assert result.exit_code == 1

    def test_login_no_args(self, tmp_path, monkeypatch):
        monkeypatch.setattr("cli.main._CONFIG_PATH", tmp_path / ".modelionn.toml")

        result = runner.invoke(app, ["login"])
        assert result.exit_code == 1
