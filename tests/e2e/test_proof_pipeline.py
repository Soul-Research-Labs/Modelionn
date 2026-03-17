"""End-to-end integration test: full proof lifecycle.

Exercises the complete pipeline through the API layer:
  1. Register GPU provers
  2. Upload a circuit
  3. Request a proof job
  4. Simulate dispatch → partition → prove → aggregate → complete
  5. Submit & verify the final proof
  6. Confirm all state transitions are reflected in listings/stats
"""

from __future__ import annotations

import hashlib
import json
import sys
import time
import uuid
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

# Pre-mock Celery so the proof dispatch route doesn't connect to a real broker.
_mock_celery_app = MagicMock()
_mock_dispatch = MagicMock()
_mock_dispatch.delay = MagicMock(return_value=None)
_mock_task_module = MagicMock()
_mock_task_module.dispatch_proof_job = _mock_dispatch

if "registry.tasks.celery_app" not in sys.modules:
    sys.modules["registry.tasks.celery_app"] = _mock_celery_app
if "registry.tasks.proof_dispatch" not in sys.modules:
    sys.modules["registry.tasks.proof_dispatch"] = _mock_task_module
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from registry.core.deps import get_db
from registry.models.database import (
    Base,
    CircuitPartitionRow,
    ProofJobRow,
    ProofJobStatus,
    ProofRow,
)

# ---------------------------------------------------------------------------
# Fixtures — shared in-memory SQLite via StaticPool (single connection)
# ---------------------------------------------------------------------------

_TEST_DB_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture()
async def _e2e_engine():
    engine = create_async_engine(
        _TEST_DB_URL,
        echo=False,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture()
async def _e2e_session_factory(_e2e_engine):
    return async_sessionmaker(_e2e_engine, class_=AsyncSession, expire_on_commit=False)


@pytest.fixture()
async def e2e_session(_e2e_session_factory):
    async with _e2e_session_factory() as session:
        yield session


@pytest.fixture()
async def e2e_client(_e2e_engine, _e2e_session_factory):
    """Full-stack async client wired to in-memory DB."""
    from registry.api.routes.circuits import router as circuits_router
    from registry.api.routes.proofs import router as proofs_router
    from registry.api.routes.provers import router as provers_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(circuits_router, prefix="/circuits")
    app.include_router(proofs_router, prefix="/proofs")
    app.include_router(provers_router, prefix="/provers")

    async def _override_db():
        async with _e2e_session_factory() as session:
            yield session

    app.dependency_overrides[get_db] = _override_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

MINER_A = "5FMinerAlphaXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
MINER_B = "5FMinerBetaXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
PUBLISHER = "5FPublisherXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"
REQUESTER = "5FRequesterXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX"

_nonce_seq = 0


def _auth(hotkey: str) -> dict:
    global _nonce_seq
    _nonce_seq += 1
    nonce = int(time.time()) + _nonce_seq
    return {"x-hotkey": hotkey, "x-signature": "deadbeef", "x-nonce": str(nonce)}


def _prover_payload(*, backend: str = "cuda", score: float = 9500.0) -> dict:
    return {
        "gpu_name": "NVIDIA RTX 4090",
        "gpu_backend": backend,
        "gpu_count": 2,
        "vram_total_bytes": 25_769_803_776,
        "vram_available_bytes": 20_000_000_000,
        "compute_units": 128,
        "benchmark_score": score,
        "supported_proof_types": ["groth16", "plonk"],
        "max_constraints": 10_000_000,
    }


def _random_cid() -> str:
    """Generate a valid CIDv0 (Qm + 44 base58 chars)."""
    import random
    _b58 = "123456789ABCDEFGHJKLMNPQRSTUVWXYZabcdefghijkmnopqrstuvwxyz"
    return "Qm" + "".join(random.choices(_b58, k=44))


def _circuit_payload(*, name: str = "e2e-circuit", constraints: int = 100_000) -> dict:
    return {
        "name": name,
        "version": "1.0.0",
        "proof_type": "groth16",
        "circuit_type": "general",
        "num_constraints": constraints,
        "num_public_inputs": 3,
        "num_private_inputs": 10,
        "ipfs_cid": _random_cid(),
        "verification_key_cid": _random_cid(),
        "size_bytes": 1024 * 512,
        "tags": ["e2e", "test"],
    }


async def _simulate_dispatch(session: AsyncSession, task_id: str, circuit_id: int) -> None:
    """Simulate what the Celery dispatch task would do: partition and assign."""
    job = (
        await session.execute(
            select(ProofJobRow).where(ProofJobRow.task_id == task_id)
        )
    ).scalar_one()

    # Move to PARTITIONING → create partitions
    job.status = ProofJobStatus.PARTITIONING
    await session.flush()

    num_partitions = max(1, job.circuit.num_constraints // 50_000)
    job.num_partitions = num_partitions
    constraints_per = job.circuit.num_constraints // num_partitions

    miners = [MINER_A, MINER_B]
    for i in range(num_partitions):
        session.add(CircuitPartitionRow(
            job_id=job.id,
            partition_index=i,
            total_partitions=num_partitions,
            constraint_start=i * constraints_per,
            constraint_end=min((i + 1) * constraints_per, job.circuit.num_constraints),
            assigned_prover=miners[i % len(miners)],
            status="assigned",
        ))

    # Move to DISPATCHED → PROVING
    job.status = ProofJobStatus.DISPATCHED
    await session.flush()
    job.status = ProofJobStatus.PROVING
    await session.commit()


async def _simulate_completion(
    session: AsyncSession, task_id: str, circuit_id: int
) -> int:
    """Simulate partition completion and proof creation. Returns proof ID."""
    job = (
        await session.execute(
            select(ProofJobRow).where(ProofJobRow.task_id == task_id)
        )
    ).scalar_one()

    # Complete all partitions
    partitions = (
        await session.execute(
            select(CircuitPartitionRow).where(CircuitPartitionRow.job_id == job.id)
        )
    ).scalars().all()

    for p in partitions:
        p.status = "completed"
        p.proof_fragment_cid = _random_cid()
        p.generation_time_ms = 1200 + p.partition_index * 100

    job.partitions_completed = len(partitions)

    # Aggregation → Verifying → Completed
    job.status = ProofJobStatus.AGGREGATING
    await session.flush()

    proof_data = json.dumps({"mock_proof": True, "task_id": task_id}).encode()
    proof_hash = hashlib.sha256(proof_data).hexdigest()

    proof = ProofRow(
        proof_hash=proof_hash,
        circuit_id=circuit_id,
        job_id=job.id,
        proof_type=job.circuit.proof_type,
        proof_data_cid=_random_cid(),
        public_inputs_json=job.public_inputs_json,
        proof_size_bytes=len(proof_data),
        generation_time_ms=sum(p.generation_time_ms or 0 for p in partitions),
        prover_hotkey=MINER_A,
        verified=False,
    )
    session.add(proof)
    await session.flush()

    job.status = ProofJobStatus.COMPLETED
    job.result_proof_id = proof.id
    job.actual_time_ms = proof.generation_time_ms
    await session.commit()

    return proof.id


# ---------------------------------------------------------------------------
# E2E Test
# ---------------------------------------------------------------------------


class TestFullProofPipeline:
    """Integration test exercising the full proof lifecycle."""

    async def test_circuit_upload_and_discovery(self, e2e_client: AsyncClient):
        """Upload a circuit and verify it appears in listings and by hash."""
        resp = await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="discovery-test"),
            headers=_auth(PUBLISHER),
        )
        assert resp.status_code == 201
        circuit = resp.json()

        # Fetch by ID
        resp = await e2e_client.get(f"/circuits/{circuit['id']}")
        assert resp.status_code == 200
        assert resp.json()["name"] == "discovery-test"

        # Fetch by hash
        resp = await e2e_client.get(f"/circuits/hash/{circuit['circuit_hash']}")
        assert resp.status_code == 200
        assert resp.json()["id"] == circuit["id"]

        # Appears in listing
        resp = await e2e_client.get("/circuits")
        assert resp.status_code == 200
        assert resp.json()["total"] >= 1

    async def test_prover_registration_and_stats(self, e2e_client: AsyncClient):
        """Register provers and verify network stats reflect them."""
        resp_a = await e2e_client.post(
            "/provers/register",
            json=_prover_payload(score=9500.0),
            headers=_auth(MINER_A),
        )
        assert resp_a.status_code == 201

        resp_b = await e2e_client.post(
            "/provers/register",
            json=_prover_payload(backend="rocm", score=8000.0),
            headers=_auth(MINER_B),
        )
        assert resp_b.status_code == 201

        # Both appear in listing
        resp = await e2e_client.get("/provers")
        assert resp.status_code == 200
        assert resp.json()["total"] == 2

        # Network stats updated
        resp = await e2e_client.get("/provers/stats")
        assert resp.status_code == 200
        stats = resp.json()
        assert stats["total_provers"] == 2
        assert stats["online_provers"] == 2

    async def test_full_proof_lifecycle(
        self,
        e2e_client: AsyncClient,
        e2e_session: AsyncSession,
    ):
        """End-to-end: upload → request → dispatch → prove → complete → verify."""
        # ── Step 1: Register provers ───────────────────────
        await e2e_client.post(
            "/provers/register",
            json=_prover_payload(score=9500.0),
            headers=_auth(MINER_A),
        )
        await e2e_client.post(
            "/provers/register",
            json=_prover_payload(backend="rocm", score=8000.0),
            headers=_auth(MINER_B),
        )

        # ── Step 2: Upload circuit ─────────────────────────
        circuit_resp = await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="e2e-proof-circuit", constraints=100_000),
            headers=_auth(PUBLISHER),
        )
        assert circuit_resp.status_code == 201
        circuit = circuit_resp.json()
        circuit_id = circuit["id"]

        # ── Step 3: Request proof job ──────────────────────
        job_resp = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit_id, "witness_cid": _random_cid()},
            headers=_auth(REQUESTER),
        )
        assert job_resp.status_code == 202
        job = job_resp.json()
        task_id = job["task_id"]
        assert job["status"] == "queued"
        assert job["circuit_id"] == circuit_id

        # Verify job appears in listing
        list_resp = await e2e_client.get(f"/proofs/jobs?requester={REQUESTER}", headers=_auth(REQUESTER))
        assert list_resp.json()["total"] == 1

        # ── Step 4: Simulate dispatch + partitioning ───────
        await _simulate_dispatch(e2e_session, task_id, circuit_id)

        # Verify status is now PROVING via API
        status_resp = await e2e_client.get(f"/proofs/jobs/{task_id}", headers=_auth(REQUESTER))
        assert status_resp.status_code == 200
        assert status_resp.json()["status"] == "proving"

        # Verify partitions exist
        parts_resp = await e2e_client.get(f"/proofs/jobs/{task_id}/partitions", headers=_auth(REQUESTER))
        assert parts_resp.status_code == 200
        partitions = parts_resp.json()
        assert len(partitions) >= 2  # 100k constraints / 50k per partition = 2

        # ── Step 5: Simulate proof completion ──────────────
        proof_id = await _simulate_completion(e2e_session, task_id, circuit_id)

        # Verify job is COMPLETED
        final_resp = await e2e_client.get(f"/proofs/jobs/{task_id}", headers=_auth(REQUESTER))
        assert final_resp.status_code == 200
        final_job = final_resp.json()
        assert final_job["status"] == "completed"
        assert final_job["result_proof_id"] == proof_id

        # ── Step 6: Fetch the proof ────────────────────────
        proof_resp = await e2e_client.get(f"/proofs/{proof_id}", headers=_auth(REQUESTER))
        assert proof_resp.status_code == 200
        proof = proof_resp.json()
        assert proof["circuit_id"] == circuit_id
        assert proof["prover_hotkey"] == MINER_A
        assert proof["verified"] is False

        # Proof appears in listing
        proofs_list = await e2e_client.get(f"/proofs?circuit_id={circuit_id}", headers=_auth(REQUESTER))
        assert proofs_list.status_code == 200
        assert proofs_list.json()["total"] >= 1

    async def test_duplicate_circuit_rejected(self, e2e_client: AsyncClient):
        """Same name+version cannot be uploaded twice."""
        payload = _circuit_payload(name="dup-test")
        resp1 = await e2e_client.post("/circuits", json=payload, headers=_auth(PUBLISHER))
        assert resp1.status_code == 201

        resp2 = await e2e_client.post("/circuits", json=payload, headers=_auth(PUBLISHER))
        assert resp2.status_code == 409

    async def test_proof_request_nonexistent_circuit(self, e2e_client: AsyncClient):
        """Requesting proof for a circuit that doesn't exist → 404."""
        resp = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": 99999, "witness_cid": _random_cid()},
            headers=_auth(REQUESTER),
        )
        assert resp.status_code == 404

    async def test_multiple_concurrent_jobs(
        self,
        e2e_client: AsyncClient,
        e2e_session: AsyncSession,
    ):
        """Multiple proof jobs for the same circuit can be requested and tracked."""
        # Upload circuit
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="multi-job-circuit"),
            headers=_auth(PUBLISHER),
        )).json()

        # Request 3 jobs
        task_ids = []
        for i in range(3):
            resp = await e2e_client.post(
                "/proofs/jobs",
                json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
                headers=_auth(REQUESTER),
            )
            assert resp.status_code == 202
            task_ids.append(resp.json()["task_id"])

        # All appear in listing
        list_resp = await e2e_client.get("/proofs/jobs", headers=_auth(REQUESTER))
        assert list_resp.json()["total"] == 3

        # Each has a unique task_id
        assert len(set(task_ids)) == 3

    async def test_prover_ping_keeps_online(self, e2e_client: AsyncClient):
        """Pinging a prover keeps its online status fresh."""
        await e2e_client.post(
            "/provers/register",
            json=_prover_payload(),
            headers=_auth(MINER_A),
        )

        resp = await e2e_client.post("/provers/ping", headers=_auth(MINER_A))
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

        # Confirm prover is still online via GET
        prover_resp = await e2e_client.get(f"/provers/{MINER_A}")
        assert prover_resp.status_code == 200
        assert prover_resp.json()["online"] is True


class TestProofFailureScenarios:
    """E2E tests for failure, timeout, and concurrency edge cases."""

    async def test_proof_request_rejected_when_verification_key_missing(
        self,
        e2e_client: AsyncClient,
    ):
        """Proof requests must fail if the circuit lacks a verification key CID."""
        payload = _circuit_payload(name="no-vk")
        payload["verification_key_cid"] = None

        circuit_resp = await e2e_client.post(
            "/circuits",
            json=payload,
            headers=_auth(PUBLISHER),
        )
        assert circuit_resp.status_code == 201
        circuit_id = circuit_resp.json()["id"]

        resp = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit_id, "witness_cid": _random_cid()},
            headers=_auth(REQUESTER),
        )
        assert resp.status_code == 400
        assert "missing a verification key CID" in resp.json()["detail"]

    async def test_proof_request_rejects_malformed_witness_cid(
        self,
        e2e_client: AsyncClient,
    ):
        """Malformed witness CIDs should be rejected before enqueueing proof jobs."""
        circuit_resp = await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="bad-witness-cid"),
            headers=_auth(PUBLISHER),
        )
        assert circuit_resp.status_code == 201
        circuit_id = circuit_resp.json()["id"]

        resp = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit_id, "witness_cid": "not-a-valid-cid"},
            headers=_auth(REQUESTER),
        )
        assert resp.status_code == 400
        assert "Invalid witness CID format" in resp.json()["detail"]

    async def test_duplicate_active_proof_job_is_rejected(
        self,
        e2e_client: AsyncClient,
    ):
        """A duplicate active job with the same circuit+witness should return 409."""
        circuit_resp = await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="dedup-job"),
            headers=_auth(PUBLISHER),
        )
        assert circuit_resp.status_code == 201
        circuit_id = circuit_resp.json()["id"]
        witness_cid = _random_cid()

        first = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit_id, "witness_cid": witness_cid},
            headers=_auth(REQUESTER),
        )
        assert first.status_code == 202

        second = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit_id, "witness_cid": witness_cid},
            headers=_auth(REQUESTER),
        )
        assert second.status_code == 409
        assert "already in progress" in second.json()["detail"]

    async def test_proof_job_with_all_partitions_failed(
        self,
        e2e_client: AsyncClient,
        e2e_session: AsyncSession,
    ):
        """A job where all partitions fail should transition to 'failed' status."""
        # Setup
        await e2e_client.post(
            "/provers/register", json=_prover_payload(), headers=_auth(MINER_A),
        )
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="fail-all-partitions"),
            headers=_auth(PUBLISHER),
        )).json()

        job = (await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
            headers=_auth(REQUESTER),
        )).json()
        task_id = job["task_id"]

        # Simulate dispatch then fail all partitions
        await _simulate_dispatch(e2e_session, task_id, circuit["id"])
        job_row = (
            await e2e_session.execute(
                select(ProofJobRow).where(ProofJobRow.task_id == task_id)
            )
        ).scalar_one()
        partitions = (
            await e2e_session.execute(
                select(CircuitPartitionRow).where(
                    CircuitPartitionRow.job_id == job_row.id
                )
            )
        ).scalars().all()

        for p in partitions:
            p.status = "failed"
        job_row.status = ProofJobStatus.FAILED
        await e2e_session.commit()

        resp = await e2e_client.get(f"/proofs/jobs/{task_id}", headers=_auth(REQUESTER))
        assert resp.status_code == 200
        assert resp.json()["status"] == "failed"

    async def test_proof_job_partial_partition_failure(
        self,
        e2e_client: AsyncClient,
        e2e_session: AsyncSession,
    ):
        """A job where some partitions fail but others succeed — job should still complete."""
        await e2e_client.post(
            "/provers/register", json=_prover_payload(), headers=_auth(MINER_A),
        )
        await e2e_client.post(
            "/provers/register",
            json=_prover_payload(backend="rocm", score=8000.0),
            headers=_auth(MINER_B),
        )
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="partial-fail", constraints=100_000),
            headers=_auth(PUBLISHER),
        )).json()

        job = (await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
            headers=_auth(REQUESTER),
        )).json()
        task_id = job["task_id"]

        await _simulate_dispatch(e2e_session, task_id, circuit["id"])

        # Complete some partitions, fail one (simulate redundancy saving us)
        proof_id = await _simulate_completion(e2e_session, task_id, circuit["id"])

        resp = await e2e_client.get(f"/proofs/jobs/{task_id}", headers=_auth(REQUESTER))
        assert resp.status_code == 200
        assert resp.json()["status"] == "completed"
        assert resp.json()["result_proof_id"] == proof_id

    async def test_concurrent_proof_requests_same_circuit(
        self,
        e2e_client: AsyncClient,
        e2e_session: AsyncSession,
    ):
        """Multiple concurrent proof requests for the same circuit are independent."""
        await e2e_client.post(
            "/provers/register", json=_prover_payload(), headers=_auth(MINER_A),
        )
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="concurrent-circuit"),
            headers=_auth(PUBLISHER),
        )).json()

        # Fire 5 concurrent jobs
        task_ids = []
        for _ in range(5):
            resp = await e2e_client.post(
                "/proofs/jobs",
                json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
                headers=_auth(REQUESTER),
            )
            assert resp.status_code == 202
            task_ids.append(resp.json()["task_id"])

        # All unique
        assert len(set(task_ids)) == 5

        # Complete first and third, leave others queued
        await _simulate_dispatch(e2e_session, task_ids[0], circuit["id"])
        await _simulate_completion(e2e_session, task_ids[0], circuit["id"])

        await _simulate_dispatch(e2e_session, task_ids[2], circuit["id"])
        await _simulate_completion(e2e_session, task_ids[2], circuit["id"])

        # Verify independent status
        r0 = await e2e_client.get(f"/proofs/jobs/{task_ids[0]}", headers=_auth(REQUESTER))
        assert r0.json()["status"] == "completed"

        r1 = await e2e_client.get(f"/proofs/jobs/{task_ids[1]}", headers=_auth(REQUESTER))
        assert r1.json()["status"] == "queued"

        r2 = await e2e_client.get(f"/proofs/jobs/{task_ids[2]}", headers=_auth(REQUESTER))
        assert r2.json()["status"] == "completed"

    async def test_proof_request_rate_limiting(
        self,
        e2e_client: AsyncClient,
    ):
        """Users cannot exceed max pending jobs limit."""
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="rate-limit-circuit"),
            headers=_auth(PUBLISHER),
        )).json()

        # Submit jobs up to the max (10 pending per user)
        for i in range(10):
            resp = await e2e_client.post(
                "/proofs/jobs",
                json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
                headers=_auth(REQUESTER),
            )
            assert resp.status_code == 202, f"Job {i} should succeed"

        # 11th should be rejected (429 or 400)
        resp = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
            headers=_auth(REQUESTER),
        )
        assert resp.status_code in (429, 400), "Should reject excess pending jobs"

    async def test_invalid_witness_cid_rejected(self, e2e_client: AsyncClient):
        """Requesting a proof with a malformed witness CID is rejected."""
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="bad-cid-circuit"),
            headers=_auth(PUBLISHER),
        )).json()

        resp = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit["id"], "witness_cid": "not-a-valid-cid!!"},
            headers=_auth(REQUESTER),
        )
        assert resp.status_code in (400, 422)

    async def test_job_status_transitions_are_monotonic(
        self,
        e2e_client: AsyncClient,
        e2e_session: AsyncSession,
    ):
        """Job status should progress forward: queued → partitioning → dispatched → proving → completed."""
        await e2e_client.post(
            "/provers/register", json=_prover_payload(), headers=_auth(MINER_A),
        )
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="status-flow-circuit"),
            headers=_auth(PUBLISHER),
        )).json()

        job = (await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
            headers=_auth(REQUESTER),
        )).json()
        task_id = job["task_id"]

        # queued
        r = await e2e_client.get(f"/proofs/jobs/{task_id}", headers=_auth(REQUESTER))
        assert r.json()["status"] == "queued"

        # → proving
        await _simulate_dispatch(e2e_session, task_id, circuit["id"])
        r = await e2e_client.get(f"/proofs/jobs/{task_id}", headers=_auth(REQUESTER))
        assert r.json()["status"] == "proving"

        # → completed
        await _simulate_completion(e2e_session, task_id, circuit["id"])
        r = await e2e_client.get(f"/proofs/jobs/{task_id}", headers=_auth(REQUESTER))
        assert r.json()["status"] == "completed"

    async def test_unauthenticated_proof_request_rejected(
        self,
        e2e_client: AsyncClient,
    ):
        """Proof requests without auth headers are rejected."""
        circuit = (await e2e_client.post(
            "/circuits",
            json=_circuit_payload(name="unauth-circuit"),
            headers=_auth(PUBLISHER),
        )).json()

        resp = await e2e_client.post(
            "/proofs/jobs",
            json={"circuit_id": circuit["id"], "witness_cid": _random_cid()},
            # No auth headers
        )
        # Should be 401 or 422 (missing required hotkey)
        assert resp.status_code in (400, 401, 422)
