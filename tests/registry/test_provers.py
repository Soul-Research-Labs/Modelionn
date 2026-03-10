"""Tests for /provers API routes — registration, ping, listing, stats."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


# ── Helpers ──────────────────────────────────────────────────

def _prover_payload(**overrides) -> dict:
    defaults = {
        "gpu_name": "NVIDIA RTX 4090",
        "gpu_backend": "cuda",
        "gpu_count": 2,
        "vram_total_bytes": 25_769_803_776,
        "vram_available_bytes": 20_000_000_000,
        "compute_units": 128,
        "benchmark_score": 9500.0,
        "supported_proof_types": ["groth16", "plonk"],
        "max_constraints": 10_000_000,
    }
    defaults.update(overrides)
    return defaults


# ── Registration ─────────────────────────────────────────────

class TestProverRegistration:
    async def test_register_new_prover(self, client: AsyncClient):
        resp = await client.post(
            "/provers/register?hotkey=5FMiner1",
            json=_prover_payload(),
        )
        assert resp.status_code == 201
        data = resp.json()
        assert data["hotkey"] == "5FMiner1"
        assert data["gpu_name"] == "NVIDIA RTX 4090"
        assert data["gpu_backend"] == "cuda"
        assert data["gpu_count"] == 2
        assert data["online"] is True
        assert data["benchmark_score"] == 9500.0

    async def test_register_upsert_existing(self, client: AsyncClient):
        await client.post(
            "/provers/register?hotkey=5FMiner1",
            json=_prover_payload(benchmark_score=5000.0),
        )
        resp = await client.post(
            "/provers/register?hotkey=5FMiner1",
            json=_prover_payload(benchmark_score=9999.0),
        )
        assert resp.status_code == 201
        assert resp.json()["benchmark_score"] == 9999.0

    async def test_register_invalid_gpu_backend_400(self, client: AsyncClient):
        resp = await client.post(
            "/provers/register?hotkey=5FMiner",
            json=_prover_payload(gpu_backend="invalid_backend"),
        )
        assert resp.status_code == 400

    async def test_register_missing_hotkey_422(self, client: AsyncClient):
        resp = await client.post("/provers/register", json=_prover_payload())
        assert resp.status_code == 422

    async def test_register_all_gpu_backends(self, client: AsyncClient):
        for backend in ["cuda", "rocm", "metal", "webgpu", "cpu"]:
            resp = await client.post(
                f"/provers/register?hotkey=5F{backend}Miner",
                json=_prover_payload(gpu_backend=backend),
            )
            assert resp.status_code == 201
            assert resp.json()["gpu_backend"] == backend


# ── Ping ─────────────────────────────────────────────────────

class TestProverPing:
    async def test_ping_registered_prover(self, client: AsyncClient):
        await client.post(
            "/provers/register?hotkey=5FMiner1",
            json=_prover_payload(),
        )
        resp = await client.post("/provers/ping?hotkey=5FMiner1&vram_available_bytes=15000000000")
        assert resp.status_code == 200
        assert resp.json()["status"] == "ok"

    async def test_ping_unregistered_prover_404(self, client: AsyncClient):
        resp = await client.post("/provers/ping?hotkey=5FUnknown&vram_available_bytes=0")
        assert resp.status_code == 404


# ── Listing ──────────────────────────────────────────────────

class TestListProvers:
    async def test_list_empty(self, client: AsyncClient):
        resp = await client.get("/provers")
        assert resp.status_code == 200
        data = resp.json()
        assert data["items"] == []
        assert data["total"] == 0

    async def test_list_with_data(self, client: AsyncClient):
        for i in range(3):
            await client.post(
                f"/provers/register?hotkey=5FMiner{i}",
                json=_prover_payload(),
            )
        resp = await client.get("/provers")
        data = resp.json()
        assert data["total"] == 3
        assert len(data["items"]) == 3

    async def test_list_online_only(self, client: AsyncClient):
        await client.post(
            "/provers/register?hotkey=5FOnline",
            json=_prover_payload(),
        )
        # The register endpoint sets online=True, so all registered are online
        resp = await client.get("/provers?online_only=true")
        data = resp.json()
        assert data["total"] >= 1
        assert all(p["online"] for p in data["items"])

    async def test_list_filter_gpu_backend(self, client: AsyncClient):
        await client.post(
            "/provers/register?hotkey=5FCuda",
            json=_prover_payload(gpu_backend="cuda"),
        )
        await client.post(
            "/provers/register?hotkey=5FMetal",
            json=_prover_payload(gpu_backend="metal"),
        )
        resp = await client.get("/provers?gpu_backend=cuda")
        data = resp.json()
        assert data["total"] == 1
        assert data["items"][0]["gpu_backend"] == "cuda"

    async def test_list_pagination(self, client: AsyncClient):
        for i in range(5):
            await client.post(
                f"/provers/register?hotkey=5FM{i}",
                json=_prover_payload(),
            )
        resp = await client.get("/provers?page=1&page_size=2")
        data = resp.json()
        assert data["total"] == 5
        assert len(data["items"]) == 2


# ── Get prover ───────────────────────────────────────────────

class TestGetProver:
    async def test_get_by_hotkey(self, client: AsyncClient):
        await client.post(
            "/provers/register?hotkey=5FMyMiner",
            json=_prover_payload(),
        )
        resp = await client.get("/provers/5FMyMiner")
        assert resp.status_code == 200
        assert resp.json()["hotkey"] == "5FMyMiner"

    async def test_get_not_found(self, client: AsyncClient):
        resp = await client.get("/provers/5FUnknownMiner")
        assert resp.status_code == 404


# ── Network stats ────────────────────────────────────────────

class TestNetworkStats:
    async def test_stats_empty(self, client: AsyncClient):
        resp = await client.get("/provers/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_provers"] == 0
        assert data["online_provers"] == 0

    async def test_stats_with_provers(self, client: AsyncClient):
        await client.post(
            "/provers/register?hotkey=5FM1",
            json=_prover_payload(gpu_count=2, vram_total_bytes=24_000_000_000),
        )
        await client.post(
            "/provers/register?hotkey=5FM2",
            json=_prover_payload(gpu_count=4, vram_total_bytes=48_000_000_000, gpu_backend="rocm"),
        )
        resp = await client.get("/provers/stats")
        data = resp.json()
        assert data["total_provers"] == 2
        assert data["online_provers"] == 2
        assert data["total_gpus"] == 6
        assert data["total_vram_bytes"] == 72_000_000_000
        assert "cuda" in data["gpu_backends"]
        assert "rocm" in data["gpu_backends"]
