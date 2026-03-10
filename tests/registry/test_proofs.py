"""Tests for /proofs API routes — proof jobs, partitions, verification."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Helpers ──────────────────────────────────────────────────

async def _create_circuit(client: AsyncClient, **overrides) -> dict:
    defaults = {
        "name": "bench-circuit",
        "version": "1.0.0",
        "proof_type": "groth16",
        "circuit_type": "general",
        "num_constraints": 50000,
        "ipfs_cid": "QmCircuitData123",
    }
    defaults.update(overrides)
    resp = await client.post("/circuits?hotkey=5FPublisher", json=defaults)
    assert resp.status_code == 201
    return resp.json()


def _proof_request(circuit_id: int, **overrides) -> dict:
    defaults = {
        "circuit_id": circuit_id,
        "witness_cid": "QmWitnessCid123",
    }
    defaults.update(overrides)
    return defaults


# ── Request proof job ────────────────────────────────────────

class TestRequestProof:
    async def test_request_success(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        resp = await client.post(
            "/proofs/jobs?hotkey=5FRequester",
            json=_proof_request(circuit["id"]),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["circuit_id"] == circuit["id"]
        assert data["requester_hotkey"] == "5FRequester"
        assert data["status"] == "queued"
        assert data["task_id"]
        assert data["num_partitions"] >= 1
        assert data["redundancy"] >= 1

    async def test_request_missing_circuit_404(self, client: AsyncClient):
        resp = await client.post(
            "/proofs/jobs?hotkey=5FReq",
            json=_proof_request(circuit_id=9999),
        )
        assert resp.status_code == 404

    async def test_request_missing_hotkey_422(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        resp = await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"]),
        )
        assert resp.status_code == 422

    async def test_request_partitioning_large_circuit(self, client: AsyncClient):
        circuit = await _create_circuit(
            client,
            name="large-circ",
            num_constraints=50_000_000,
            ipfs_cid="QmLarge",
        )
        resp = await client.post(
            "/proofs/jobs?hotkey=5FReq",
            json=_proof_request(circuit["id"]),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["num_partitions"] > 1


# ── Get proof job ────────────────────────────────────────────

class TestGetProofJob:
    async def test_get_job_by_task_id(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        create = await client.post(
            "/proofs/jobs?hotkey=5FReq",
            json=_proof_request(circuit["id"]),
        )
        task_id = create.json()["task_id"]
        resp = await client.get(f"/proofs/jobs/{task_id}")
        assert resp.status_code == 200
        assert resp.json()["task_id"] == task_id

    async def test_get_job_not_found(self, client: AsyncClient):
        resp = await client.get("/proofs/jobs/nonexistent")
        assert resp.status_code == 404


# ── List proof jobs ──────────────────────────────────────────

class TestListProofJobs:
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/proofs/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_with_data(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        for i in range(3):
            await client.post(
                f"/proofs/jobs?hotkey=5FReq{i}",
                json=_proof_request(circuit["id"], witness_cid=f"QmW{i}"),
            )
        resp = await client.get("/proofs/jobs")
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_list_filter_by_requester(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        await client.post(
            "/proofs/jobs?hotkey=5FAlice",
            json=_proof_request(circuit["id"], witness_cid="QmWA"),
        )
        await client.post(
            "/proofs/jobs?hotkey=5FBob",
            json=_proof_request(circuit["id"], witness_cid="QmWB"),
        )
        resp = await client.get("/proofs/jobs?requester=5FAlice")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["requester_hotkey"] == "5FAlice"

    async def test_list_pagination(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        for i in range(5):
            await client.post(
                f"/proofs/jobs?hotkey=5FReq{i}",
                json=_proof_request(circuit["id"], witness_cid=f"QmW{i}"),
            )
        resp = await client.get("/proofs/jobs?page=1&page_size=2")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2


# ── List proofs ──────────────────────────────────────────────

class TestListProofs:
    async def test_list_proofs_empty(self, client: AsyncClient):
        resp = await client.get("/proofs")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


# ── Get proof ────────────────────────────────────────────────

class TestGetProof:
    async def test_get_proof_not_found(self, client: AsyncClient):
        resp = await client.get("/proofs/999")
        assert resp.status_code == 404


# ── Verify ───────────────────────────────────────────────────

class TestVerifyProof:
    async def test_verify_not_found(self, client: AsyncClient):
        resp = await client.post(
            "/proofs/verify",
            json={"proof_id": 999},
        )
        assert resp.status_code == 404


# ── Job partitions ───────────────────────────────────────────

class TestJobPartitions:
    async def test_get_partitions_empty(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        create = await client.post(
            "/proofs/jobs?hotkey=5FReq",
            json=_proof_request(circuit["id"]),
        )
        task_id = create.json()["task_id"]
        resp = await client.get(f"/proofs/jobs/{task_id}/partitions")
        assert resp.status_code == 200
        # No partitions created by API alone — dispatched by Celery
        assert isinstance(resp.json(), list)

    async def test_get_partitions_job_not_found(self, client: AsyncClient):
        resp = await client.get("/proofs/jobs/nonexistent/partitions")
        assert resp.status_code == 404
