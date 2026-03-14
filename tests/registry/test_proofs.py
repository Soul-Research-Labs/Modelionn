"""Tests for /proofs API routes — proof jobs, partitions, verification."""

from __future__ import annotations

import pytest
import time

from httpx import AsyncClient


_nonce_seq = 0


def _auth(hotkey="5FTestPublisherXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"):
    global _nonce_seq
    _nonce_seq += 1
    nonce = int(time.time()) + _nonce_seq
    return {"x-hotkey": hotkey, "x-signature": "deadbeef", "x-nonce": str(nonce)}


# ── Helpers ──────────────────────────────────────────────────

# Valid CIDv0: Qm + 44 base58 chars
_VALID_CID = "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG"
_VALID_WITNESS_CID = "QmT5NvUtoM5nWFfrQnVFwHvBpiFkHjbGEhYbTnTEt5aYrj"


async def _create_circuit(client: AsyncClient, **overrides) -> dict:
    defaults = {
        "name": "bench-circuit",
        "version": "1.0.0",
        "proof_type": "groth16",
        "circuit_type": "general",
        "num_constraints": 50000,
        "ipfs_cid": _VALID_CID,
        "verification_key_cid": _VALID_CID,
    }
    defaults.update(overrides)
    resp = await client.post("/circuits", json=defaults, headers=_auth())
    assert resp.status_code == 201
    return resp.json()


def _proof_request(circuit_id: int, **overrides) -> dict:
    defaults = {
        "circuit_id": circuit_id,
        "witness_cid": _VALID_WITNESS_CID,
    }
    defaults.update(overrides)
    return defaults


# ── Request proof job ────────────────────────────────────────

class TestRequestProof:
    async def test_request_success(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        resp = await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"]),
            headers=_auth(),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["circuit_id"] == circuit["id"]
        assert data["requester_hotkey"] == "5FTestPublisherXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        assert data["status"] == "queued"
        assert data["task_id"]
        assert data["num_partitions"] >= 1
        assert data["redundancy"] >= 1

    async def test_request_missing_circuit_404(self, client: AsyncClient):
        resp = await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit_id=9999),
            headers=_auth(),
        )
        assert resp.status_code == 404

    async def test_request_missing_hotkey_422(self, client: AsyncClient):
        """Omitting auth headers should return 422 (missing x-hotkey header)."""
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
            ipfs_cid="QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn",
            verification_key_cid="QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn",
        )
        resp = await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"]),
            headers=_auth(),
        )
        assert resp.status_code == 202
        data = resp.json()
        assert data["num_partitions"] > 1

    async def test_request_missing_verification_key_400(self, client: AsyncClient):
        """Circuit without a verification_key_cid should be rejected."""
        circuit = await _create_circuit(
            client,
            name="no-vk-circuit",
            verification_key_cid=None,
        )
        resp = await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"]),
            headers=_auth(),
        )
        assert resp.status_code == 400
        assert "verification key" in resp.json()["detail"].lower()


# ── Get proof job ────────────────────────────────────────────

class TestGetProofJob:
    async def test_get_job_by_task_id(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        create = await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"]),
            headers=_auth(),
        )
        task_id = create.json()["task_id"]
        resp = await client.get(f"/proofs/jobs/{task_id}", headers=_auth())
        assert resp.status_code == 200
        assert resp.json()["task_id"] == task_id

    async def test_get_job_not_found(self, client: AsyncClient):
        resp = await client.get("/proofs/jobs/nonexistent", headers=_auth())
        assert resp.status_code == 404


# ── List proof jobs ──────────────────────────────────────────

class TestListProofJobs:
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/proofs/jobs", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_with_data(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        witness_cids = [
            "QmSsw6EcnwEiTT9c4rnAGeSENvsJMepNHmbrgi2S9bXNjm",
            "QmbWqxBEKC3P8tqsKc98xmWNzrzDtRLMiMPL8wBuTGsMnR",
            "QmTzQ1JRkWErjk39mryYw2WVaphAZNAREyMchXzYQ7c15n",
        ]
        for i in range(3):
            await client.post(
                f"/proofs/jobs",
                json=_proof_request(circuit["id"], witness_cid=witness_cids[i]),
                headers=_auth(),
            )
        resp = await client.get("/proofs/jobs", headers=_auth())
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_list_filter_by_requester(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        alice = "5FAliceXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
        await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"], witness_cid="QmW2WQi7j6c7UgJTarActp7tDNikE4B2qXtFCfLPdsgaTQ"),
            headers=_auth(alice),
        )
        await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"], witness_cid="QmRf22bZar3WKmojipms22PkXH1MZGmvsqzQtuSvQE3uhm"),
            headers=_auth(),
        )
        resp = await client.get(f"/proofs/jobs?requester={alice}", headers=_auth(alice))
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["requester_hotkey"] == alice

    async def test_list_pagination(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        witness_page_cids = [
            "QmVE7b6qVAPo93rG2Vj1zRz7WMXQ5YsMDMBqxfPniXMV5G",
            "QmXoypizjW3WknFiJnKLwHCnL72vedxjQkDDP1mXWo6uco",
            "QmZTR5bcpQD7cFgTorqxZDYaew1Wqgfbd2ud9QqGPAkK2V",
            "QmaozNR7DZHQK1ZcU9p7QdrshMvXqWK6gpu5rmrkPdT3L4",
            "QmcRD4wkPPi6dig81r5sLj9Zm1gDCL4zgpEj9CfuRrGbzF",
        ]
        for i in range(5):
            await client.post(
                f"/proofs/jobs",
                json=_proof_request(circuit["id"], witness_cid=witness_page_cids[i]),
                headers=_auth(),
            )
        resp = await client.get("/proofs/jobs?page=1&page_size=2", headers=_auth())
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2


# ── List proofs ──────────────────────────────────────────────

class TestListProofs:
    async def test_list_proofs_empty(self, client: AsyncClient):
        resp = await client.get("/proofs", headers=_auth())
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0


# ── Get proof ────────────────────────────────────────────────

class TestGetProof:
    async def test_get_proof_not_found(self, client: AsyncClient):
        resp = await client.get("/proofs/999", headers=_auth())
        assert resp.status_code == 404


# ── Verify ───────────────────────────────────────────────────

class TestVerifyProof:
    async def test_verify_not_found(self, client: AsyncClient):
        resp = await client.post(
            "/proofs/verify",
            json={"proof_id": 999},
            headers=_auth(),
        )
        assert resp.status_code == 404


# ── Job partitions ───────────────────────────────────────────

class TestJobPartitions:
    async def test_get_partitions_empty(self, client: AsyncClient):
        circuit = await _create_circuit(client)
        create = await client.post(
            "/proofs/jobs",
            json=_proof_request(circuit["id"]),
            headers=_auth(),
        )
        task_id = create.json()["task_id"]
        resp = await client.get(f"/proofs/jobs/{task_id}/partitions", headers=_auth())
        assert resp.status_code == 200
        # No partitions created by API alone — dispatched by Celery
        assert isinstance(resp.json(), list)

    async def test_get_partitions_job_not_found(self, client: AsyncClient):
        resp = await client.get("/proofs/jobs/nonexistent/partitions", headers=_auth())
        assert resp.status_code == 404
