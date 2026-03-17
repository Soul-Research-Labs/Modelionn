"""Locust load tests for the Modelionn Registry API.

Usage:
    locust -f tests/load/locustfile.py --host http://localhost:8000

See tests/load/README.md for details.
"""

from __future__ import annotations

import os
import random
import time

from locust import HttpUser, LoadTestShape, between, task


# ── Helper ──────────────────────────────────────────────────


def _auth_headers() -> dict[str, str]:
    """Generate authentication headers if MODELIONN_HOTKEY is set."""
    hotkey = os.environ.get("MODELIONN_HOTKEY", "")
    if not hotkey:
        return {}
    nonce = str(int(time.time()))
    # In real usage, sign_fn would produce a real signature.
    # For load testing, the server should be in debug mode or signatures disabled.
    return {
        "x-hotkey": hotkey,
        "x-nonce": nonce,
        "x-signature": "load-test-signature",
    }


# ── Read-Heavy User ─────────────────────────────────────────


class ReadOnlyUser(HttpUser):
    """Simulates users browsing circuits, provers, and network stats."""

    weight = 5
    wait_time = between(1, 3)

    @task(5)
    def list_circuits(self):
        page = random.randint(1, 5)
        self.client.get(f"/circuits?page={page}&page_size=20", name="/circuits")

    @task(3)
    def get_circuit(self):
        circuit_id = random.randint(1, 100)
        with self.client.get(
            f"/circuits/{circuit_id}",
            name="/circuits/[id]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()  # Expected for non-existent circuits

    @task(4)
    def list_provers(self):
        self.client.get("/provers?page=1&page_size=20", name="/provers")

    @task(3)
    def get_network_stats(self):
        self.client.get("/provers/stats", name="/provers/stats")

    @task(2)
    def health_check(self):
        self.client.get("/health", name="/health")

    @task(1)
    def health_ready(self):
        self.client.get("/health/ready", name="/health/ready")


# ── Proof Requester User ────────────────────────────────────


class ProofRequester(HttpUser):
    """Simulates users requesting and polling proof jobs."""

    weight = 2
    wait_time = between(2, 5)

    def on_start(self):
        self._active_jobs: list[str] = []

    @task(3)
    def request_proof(self):
        headers = _auth_headers()
        if not headers:
            return  # Skip if no auth configured

        circuit_id = random.randint(1, 50)
        with self.client.post(
            "/proofs/jobs",
            json={
                "circuit_id": circuit_id,
                "witness_cid": f"Qm{'a' * 44}",
            },
            headers=headers,
            name="/proofs/jobs [POST]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 200:
                data = resp.json()
                task_id = data.get("task_id")
                if task_id:
                    self._active_jobs.append(task_id)
                    # Cap tracked jobs
                    if len(self._active_jobs) > 20:
                        self._active_jobs = self._active_jobs[-20:]
            elif resp.status_code in (404, 422, 429):
                resp.success()  # Expected errors

    @task(5)
    def poll_job_status(self):
        if not self._active_jobs:
            return
        task_id = random.choice(self._active_jobs)
        headers = _auth_headers()
        with self.client.get(
            f"/proofs/jobs/{task_id}",
            headers=headers,
            name="/proofs/jobs/[id]",
            catch_response=True,
        ) as resp:
            if resp.status_code == 404:
                resp.success()
                self._active_jobs.remove(task_id)

    @task(2)
    def list_proof_jobs(self):
        headers = _auth_headers()
        if not headers:
            return
        self.client.get(
            "/proofs/jobs?page=1&page_size=20",
            headers=headers,
            name="/proofs/jobs [GET]",
        )

    @task(1)
    def list_proofs(self):
        headers = _auth_headers()
        if not headers:
            return
        self.client.get(
            "/proofs?page=1&page_size=20",
            headers=headers,
            name="/proofs [GET]",
        )


# ── Admin User ──────────────────────────────────────────────


class AdminUser(HttpUser):
    """Simulates admin operations: orgs, API keys, audit logs."""

    weight = 1
    wait_time = between(3, 8)

    @task(3)
    def list_circuits(self):
        self.client.get("/circuits?page=1&page_size=50", name="/circuits [admin]")

    @task(2)
    def list_provers(self):
        self.client.get("/provers?page=1&page_size=50", name="/provers [admin]")

    @task(2)
    def list_orgs(self):
        headers = _auth_headers()
        if not headers:
            return
        with self.client.get(
            "/orgs",
            headers=headers,
            name="/orgs",
            catch_response=True,
        ) as resp:
            if resp.status_code in (401, 403):
                resp.success()

    @task(1)
    def list_audit_logs(self):
        headers = _auth_headers()
        if not headers:
            return
        with self.client.get(
            "/audit?page=1&page_size=50",
            headers=headers,
            name="/audit",
            catch_response=True,
        ) as resp:
            if resp.status_code in (401, 403):
                resp.success()

    @task(1)
    def list_api_keys(self):
        headers = _auth_headers()
        if not headers:
            return
        with self.client.get(
            "/api-keys",
            headers=headers,
            name="/api-keys",
            catch_response=True,
        ) as resp:
            if resp.status_code in (401, 403):
                resp.success()

class SpikeLoadShape(LoadTestShape):
    """Spike and cooldown profile for proof API load testing."""

    stages = [
        {"duration": 60, "users": 10, "spawn_rate": 2},     # Warm-up
        {"duration": 120, "users": 50, "spawn_rate": 10},   # Spike
        {"duration": 240, "users": 20, "spawn_rate": 5},    # Sustained
        {"duration": 300, "users": 0, "spawn_rate": 5},     # Cool-down
    ]

    def tick(self):
        run_time = self.get_run_time()
        for stage in self.stages:
            if run_time < stage["duration"]:
                return stage["users"], stage["spawn_rate"]
        return None
