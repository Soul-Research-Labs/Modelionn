"""Modelionn Python SDK — ZK prover network client."""

from __future__ import annotations

import logging
import os
import time
from typing import Any

import httpx

from sdk.errors import (
    ModelionnError,
    RateLimitError,
    raise_for_status,
)

logger = logging.getLogger(__name__)

# ── Retry defaults ───────────────────────────────────────────
_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE = 1.0  # seconds
_DEFAULT_BACKOFF_CAP = 15.0  # seconds


def _sleep_backoff(attempt: int, base: float = _DEFAULT_BACKOFF_BASE, cap: float = _DEFAULT_BACKOFF_CAP) -> None:
    """Exponential backoff: base * 2^attempt, capped."""
    delay = min(base * (2 ** attempt), cap)
    time.sleep(delay)


class ModelionnClient:
    """Client for the Modelionn ZK Prover Network API.

    Usage::

        client = ModelionnClient("http://localhost:8000")
        circuit = client.upload_circuit(name="test", version="1.0", ...)
        job = client.request_proof(circuit_id=1, witness_cid="Qm...")
        status = client.get_proof_job(job["task_id"])
    """

    def __init__(
        self,
        registry_url: str = "http://localhost:8000",
        hotkey: str = "",
        sign_fn: Any = None,
        *,
        max_retries: int = _DEFAULT_MAX_RETRIES,
        backoff_base: float = _DEFAULT_BACKOFF_BASE,
        backoff_cap: float = _DEFAULT_BACKOFF_CAP,
    ) -> None:
        self._url = registry_url.rstrip("/")
        self._hotkey = hotkey
        self._sign_fn = sign_fn
        self._max_retries = max_retries
        self._backoff_base = backoff_base
        self._backoff_cap = backoff_cap
        self._http: httpx.Client | None = None

    def _get_http(self, timeout: int = 30) -> httpx.Client:
        """Return a persistent httpx client with connection pooling."""
        if self._http is None or self._http.is_closed:
            self._http = httpx.Client(
                timeout=timeout,
                limits=httpx.Limits(max_connections=10, max_keepalive_connections=5),
            )
        return self._http

    def __enter__(self) -> ModelionnClient:
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTP connection pool."""
        if self._http is not None and not self._http.is_closed:
            self._http.close()
            self._http = None

    def __del__(self) -> None:
        self.close()

    # ── Auth helpers ─────────────────────────────────────────

    def _auth_headers(self) -> dict[str, str]:
        if not self._hotkey:
            return {}
        nonce = str(int(time.time()))
        message = f"{self._hotkey}:{nonce}"
        if self._sign_fn:
            sig = self._sign_fn(message)
        else:
            raise ModelionnError(
                "sign_fn is required for authenticated requests. "
                "Provide a signing function (e.g. bittensor Keypair.sign) when "
                "constructing ModelionnClient."
            )
        return {
            "x-hotkey": self._hotkey,
            "x-nonce": nonce,
            "x-signature": sig,
        }

    # ── Retry wrapper ────────────────────────────────────────

    def _request_with_retry(
        self,
        method: str,
        url: str,
        *,
        timeout: int = 30,
        **kwargs: Any,
    ) -> httpx.Response:
        """Execute an HTTP request with retry + exponential backoff.

        Retries on 429, 502, 503, 504, and connection errors.
        """
        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                client = self._get_http(timeout)
                resp = client.request(method, url, **kwargs)
                if resp.status_code == 429:
                    if attempt < self._max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        delay = int(retry_after) if retry_after and retry_after.isdigit() else None
                        if delay:
                            time.sleep(delay)
                        else:
                            _sleep_backoff(attempt, self._backoff_base, self._backoff_cap)
                        continue
                    raise_for_status(resp.status_code, resp.text)
                if resp.status_code in (502, 503, 504) and attempt < self._max_retries:
                    _sleep_backoff(attempt, self._backoff_base, self._backoff_cap)
                    continue
                raise_for_status(resp.status_code, resp.text)
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    _sleep_backoff(attempt, self._backoff_base, self._backoff_cap)
                    continue
                raise ModelionnError(f"Connection failed after {self._max_retries + 1} attempts: {exc}") from exc
            except (ModelionnError, RateLimitError):
                raise
        # Should not reach here, but just in case
        raise ModelionnError(f"Request failed after {self._max_retries + 1} attempts") from last_exc

    # ── ZK Circuits ────────────────────────────────────────────

    def list_circuits(
        self,
        *,
        proof_type: str | None = None,
        circuit_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """List available ZK circuits."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if proof_type:
            params["proof_type"] = proof_type
        if circuit_type:
            params["circuit_type"] = circuit_type
        resp = self._request_with_retry("GET", f"{self._url}/circuits", params=params)
        return resp.json()

    def get_circuit(self, circuit_id: int) -> dict[str, Any]:
        """Get circuit details by ID."""
        resp = self._request_with_retry("GET", f"{self._url}/circuits/{circuit_id}")
        return resp.json()

    def upload_circuit(
        self,
        *,
        name: str,
        version: str,
        proof_type: str,
        circuit_type: str = "general",
        num_constraints: int,
        data_cid: str,
        proving_key_cid: str = "",
        verification_key_cid: str = "",
    ) -> dict[str, Any]:
        """Upload a new ZK circuit to the registry."""
        resp = self._request_with_retry(
            "POST",
            f"{self._url}/circuits",
            json={
                "name": name,
                "version": version,
                "proof_type": proof_type,
                "circuit_type": circuit_type,
                "num_constraints": num_constraints,
                "data_cid": data_cid,
                "proving_key_cid": proving_key_cid,
                "verification_key_cid": verification_key_cid,
                "publisher_hotkey": self._hotkey,
            },
            headers=self._auth_headers(),
        )
        return resp.json()

    # ── ZK Proof Jobs ────────────────────────────────────────

    def request_proof(
        self,
        circuit_id: int,
        witness_cid: str,
        *,
        num_partitions: int = 4,
        redundancy: int = 2,
    ) -> dict[str, Any]:
        """Submit a proof generation request."""
        resp = self._request_with_retry(
            "POST",
            f"{self._url}/proofs/jobs",
            json={
                "circuit_id": circuit_id,
                "witness_cid": witness_cid,
                "requester_hotkey": self._hotkey,
                "num_partitions": num_partitions,
                "redundancy": redundancy,
            },
            headers=self._auth_headers(),
        )
        return resp.json()

    def get_proof_job(self, task_id: str) -> dict[str, Any]:
        """Get proof job status."""
        resp = self._request_with_retry("GET", f"{self._url}/proofs/jobs/{task_id}")
        return resp.json()

    def list_proof_jobs(self, *, status: str | None = None, page: int = 1) -> dict[str, Any]:
        """List proof jobs."""
        params: dict[str, Any] = {"page": page}
        if status:
            params["status"] = status
        resp = self._request_with_retry("GET", f"{self._url}/proofs/jobs", params=params)
        return resp.json()

    def verify_proof(self, proof_id: int, verification_key_cid: str, public_inputs_json: str = "{}") -> dict[str, Any]:
        """Verify a completed proof."""
        resp = self._request_with_retry(
            "POST",
            f"{self._url}/proofs/verify",
            json={
                "proof_id": proof_id,
                "verification_key_cid": verification_key_cid,
                "public_inputs_json": public_inputs_json,
            },
            headers=self._auth_headers(),
        )
        return resp.json()

    # ── ZK Provers (Network) ─────────────────────────────────

    def list_provers(self, *, online_only: bool = False, page: int = 1) -> dict[str, Any]:
        """List provers in the network."""
        params: dict[str, Any] = {"page": page}
        if online_only:
            params["online_only"] = "true"
        resp = self._request_with_retry("GET", f"{self._url}/provers", params=params)
        return resp.json()

    def get_network_stats(self) -> dict[str, Any]:
        """Get network-wide prover statistics."""
        resp = self._request_with_retry("GET", f"{self._url}/provers/stats")
        return resp.json()

    def get_prover(self, hotkey: str) -> dict[str, Any]:
        """Get prover details by hotkey."""
        resp = self._request_with_retry("GET", f"{self._url}/provers/{hotkey}")
        return resp.json()

    def register_prover(self, **capabilities: Any) -> dict[str, Any]:
        """Register this node as a prover with its GPU capabilities."""
        resp = self._request_with_retry(
            "POST",
            f"{self._url}/provers/register",
            params={"hotkey": self._hotkey},
            json=capabilities,
            headers=self._auth_headers(),
        )
        return resp.json()

    def ping_prover(self, *, vram_available_bytes: int = 0) -> dict[str, Any]:
        """Send a heartbeat ping to keep prover online."""
        resp = self._request_with_retry(
            "POST",
            f"{self._url}/provers/ping",
            params={"hotkey": self._hotkey, "vram_available_bytes": vram_available_bytes},
            headers=self._auth_headers(),
        )
        return resp.json()

    # ── ZK Proofs ────────────────────────────────────────────

    def get_proof(self, proof_id: int) -> dict[str, Any]:
        """Get proof details by ID."""
        resp = self._request_with_retry("GET", f"{self._url}/proofs/{proof_id}")
        return resp.json()

    def list_proofs(
        self,
        *,
        circuit_id: int | None = None,
        verified: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        """List generated proofs with optional filters."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if circuit_id is not None:
            params["circuit_id"] = circuit_id
        if verified is not None:
            params["verified"] = str(verified).lower()
        resp = self._request_with_retry("GET", f"{self._url}/proofs", params=params)
        return resp.json()

    def get_job_partitions(self, task_id: str) -> list[dict[str, Any]]:
        """Get partition-level status for a proof job."""
        resp = self._request_with_retry("GET", f"{self._url}/proofs/jobs/{task_id}/partitions")
        return resp.json()

    # ── Organizations ────────────────────────────────────────

    def list_my_orgs(self) -> list[dict[str, Any]]:
        """List organizations the authenticated user belongs to."""
        resp = self._request_with_retry(
            "GET", f"{self._url}/orgs/me", headers=self._auth_headers(),
        )
        return resp.json()

    def get_org(self, slug: str) -> dict[str, Any]:
        """Get organization by slug."""
        resp = self._request_with_retry("GET", f"{self._url}/orgs/{slug}")
        return resp.json()

    def create_org(self, *, name: str, slug: str) -> dict[str, Any]:
        """Create a new organization."""
        resp = self._request_with_retry(
            "POST", f"{self._url}/orgs",
            json={"name": name, "slug": slug},
            headers=self._auth_headers(),
        )
        return resp.json()

    def list_members(self, slug: str, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        """List members of an organization."""
        resp = self._request_with_retry(
            "GET", f"{self._url}/orgs/{slug}/members",
            params={"page": page, "page_size": page_size},
        )
        return resp.json()

    def add_member(self, slug: str, *, hotkey: str, role: str = "viewer") -> dict[str, Any]:
        """Add a member to an organization (requires ADMIN role)."""
        resp = self._request_with_retry(
            "POST", f"{self._url}/orgs/{slug}/members",
            params={"hotkey": hotkey, "role": role},
            headers=self._auth_headers(),
        )
        return resp.json()

    def update_member_role(self, slug: str, member_hotkey: str, *, role: str) -> dict[str, Any]:
        """Update a member's role in an organization (requires ADMIN role)."""
        resp = self._request_with_retry(
            "PATCH", f"{self._url}/orgs/{slug}/members/{member_hotkey}",
            params={"role": role},
            headers=self._auth_headers(),
        )
        return resp.json()

    def remove_member(self, slug: str, member_hotkey: str) -> None:
        """Remove a member from an organization (requires ADMIN role)."""
        self._request_with_retry(
            "DELETE", f"{self._url}/orgs/{slug}/members/{member_hotkey}",
            headers=self._auth_headers(),
        )

    # ── API Keys ─────────────────────────────────────────────

    def create_api_key(self, *, label: str = "", daily_limit: int = 1000) -> dict[str, Any]:
        """Create a new API key. Returns the key in plaintext (only time it's visible)."""
        resp = self._request_with_retry(
            "POST", f"{self._url}/api-keys",
            json={"label": label, "daily_limit": daily_limit},
            headers=self._auth_headers(),
        )
        return resp.json()

    def list_api_keys(self, *, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        """List API keys for the authenticated user."""
        resp = self._request_with_retry(
            "GET", f"{self._url}/api-keys",
            params={"page": page, "page_size": page_size},
            headers=self._auth_headers(),
        )
        return resp.json()

    def revoke_api_key(self, key_id: int) -> None:
        """Revoke (delete) an API key."""
        self._request_with_retry(
            "DELETE", f"{self._url}/api-keys/{key_id}",
            headers=self._auth_headers(),
        )

    # ── Audit Logs ───────────────────────────────────────────

    def list_audit_logs(
        self,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        actor_hotkey: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        """List audit logs visible to the authenticated user (scoped to their orgs)."""
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if action:
            params["action"] = action
        if resource_type:
            params["resource_type"] = resource_type
        if actor_hotkey:
            params["actor_hotkey"] = actor_hotkey
        resp = self._request_with_retry(
            "GET", f"{self._url}/audit",
            params=params,
            headers=self._auth_headers(),
        )
        return resp.json()

    def export_audit_csv(
        self,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        from_date: str | None = None,
        to_date: str | None = None,
        limit: int = 10_000,
    ) -> bytes:
        """Export audit logs as CSV bytes (scoped to caller's orgs)."""
        params: dict[str, Any] = {"limit": limit}
        if action:
            params["action"] = action
        if resource_type:
            params["resource_type"] = resource_type
        if from_date:
            params["from_date"] = from_date
        if to_date:
            params["to_date"] = to_date
        resp = self._request_with_retry(
            "GET", f"{self._url}/audit/export",
            params=params,
            headers=self._auth_headers(),
        )
        return resp.content

    # ── Streaming downloads ──────────────────────────────────

    def download_proof(
        self,
        proof_id: int,
        output_path: str | os.PathLike[str],
        *,
        chunk_size: int = 64 * 1024,
    ) -> int:
        """Stream-download proof data to a local file.

        Avoids holding large proofs (>100MB) in memory.
        Returns the number of bytes written.
        """
        proof = self.get_proof(proof_id)
        cid = proof.get("proof_data_cid")
        if not cid:
            raise ModelionnError(f"Proof {proof_id} has no proof_data_cid")

        url = f"{self._url}/proofs/{proof_id}/download"
        client = self._get_http(timeout=300)
        written = 0
        with client.stream("GET", url, headers=self._auth_headers()) as stream:
            raise_for_status(stream.status_code, "")
            with open(output_path, "wb") as f:
                for chunk in stream.iter_bytes(chunk_size):
                    f.write(chunk)
                    written += len(chunk)
        logger.info("Downloaded proof %d → %s (%d bytes)", proof_id, output_path, written)
        return written

    # ── Batch operations ─────────────────────────────────────

    def batch_upload_circuits(
        self,
        circuits: list[dict[str, Any]],
        *,
        max_concurrency: int = 5,
    ) -> list[dict[str, Any]]:
        """Upload multiple circuits concurrently.

        Each dict in *circuits* must contain the keyword arguments for
        :meth:`upload_circuit` (name, version, proof_type, etc.).

        Returns a list of results in the same order.  Each entry is either
        the API response dict or a dict with ``{"error": "<message>"}``.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[dict[str, Any] | None] = [None] * len(circuits)

        def _upload(idx: int, kwargs: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            try:
                return idx, self.upload_circuit(**kwargs)
            except Exception as exc:
                return idx, {"error": str(exc)}

        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {
                pool.submit(_upload, i, c): i for i, c in enumerate(circuits)
            }
            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return results  # type: ignore[return-value]

    def batch_request_proofs(
        self,
        requests: list[dict[str, Any]],
        *,
        max_concurrency: int = 5,
    ) -> list[dict[str, Any]]:
        """Request multiple proof jobs concurrently.

        Each dict must contain keyword arguments for :meth:`request_proof`
        (circuit_id, witness_cid, etc.).

        Returns a list of results in the same order.
        """
        from concurrent.futures import ThreadPoolExecutor, as_completed

        results: list[dict[str, Any] | None] = [None] * len(requests)

        def _request(idx: int, kwargs: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            try:
                return idx, self.request_proof(**kwargs)
            except Exception as exc:
                return idx, {"error": str(exc)}

        with ThreadPoolExecutor(max_workers=max_concurrency) as pool:
            futures = {
                pool.submit(_request, i, r): i for i, r in enumerate(requests)
            }
            for future in as_completed(futures):
                idx, result = future.result()
                results[idx] = result

        return results  # type: ignore[return-value]
