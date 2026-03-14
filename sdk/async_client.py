"""Modelionn Async Python SDK — async ZK prover network client.

Mirrors :class:`ModelionnClient` but uses ``httpx.AsyncClient`` for
non-blocking I/O, suitable for validators, batch scripts, and high-concurrency
callers.
"""

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

_DEFAULT_MAX_RETRIES = 3
_DEFAULT_BACKOFF_BASE = 1.0
_DEFAULT_BACKOFF_CAP = 15.0


class AsyncModelionnClient:
    """Async client for the Modelionn ZK Prover Network API.

    Usage::

        async with AsyncModelionnClient("http://localhost:8000") as client:
            circuits = await client.list_circuits()
            job = await client.request_proof(circuit_id=1, witness_cid="Qm...")
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
        self._http: httpx.AsyncClient | None = None

    async def _get_http(self, timeout: int = 30) -> httpx.AsyncClient:
        if self._http is None or self._http.is_closed:
            self._http = httpx.AsyncClient(
                timeout=timeout,
                limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
            )
        return self._http

    async def __aenter__(self) -> AsyncModelionnClient:
        return self

    async def __aexit__(self, *args: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._http is not None and not self._http.is_closed:
            await self._http.aclose()
            self._http = None

    # ── Auth ─────────────────────────────────────────────────

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
                "constructing AsyncModelionnClient."
            )
        return {
            "x-hotkey": self._hotkey,
            "x-nonce": nonce,
            "x-signature": sig,
        }

    # ── Retry wrapper ────────────────────────────────────────

    async def _request(
        self,
        method: str,
        url: str,
        *,
        timeout: int = 30,
        **kwargs: Any,
    ) -> httpx.Response:
        import asyncio

        last_exc: Exception | None = None
        for attempt in range(self._max_retries + 1):
            try:
                client = await self._get_http(timeout)
                resp = await client.request(method, url, **kwargs)
                if resp.status_code == 429:
                    if attempt < self._max_retries:
                        retry_after = resp.headers.get("Retry-After")
                        delay = int(retry_after) if retry_after and retry_after.isdigit() else None
                        if delay:
                            await asyncio.sleep(delay)
                        else:
                            await asyncio.sleep(min(self._backoff_base * (2 ** attempt), self._backoff_cap))
                        continue
                    raise_for_status(resp.status_code, resp.text)
                if resp.status_code in (502, 503, 504) and attempt < self._max_retries:
                    await asyncio.sleep(min(self._backoff_base * (2 ** attempt), self._backoff_cap))
                    continue
                raise_for_status(resp.status_code, resp.text)
                return resp
            except (httpx.ConnectError, httpx.TimeoutException) as exc:
                last_exc = exc
                if attempt < self._max_retries:
                    await asyncio.sleep(min(self._backoff_base * (2 ** attempt), self._backoff_cap))
                    continue
                raise ModelionnError(f"Connection failed after {self._max_retries + 1} attempts: {exc}") from exc
            except (ModelionnError, RateLimitError):
                raise
        raise ModelionnError(f"Request failed after {self._max_retries + 1} attempts") from last_exc

    # ── ZK Circuits ──────────────────────────────────────────

    async def list_circuits(
        self,
        *,
        proof_type: str | None = None,
        circuit_type: str | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if proof_type:
            params["proof_type"] = proof_type
        if circuit_type:
            params["circuit_type"] = circuit_type
        resp = await self._request("GET", f"{self._url}/circuits", params=params)
        return resp.json()

    async def get_circuit(self, circuit_id: int) -> dict[str, Any]:
        resp = await self._request("GET", f"{self._url}/circuits/{circuit_id}")
        return resp.json()

    async def upload_circuit(
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
        resp = await self._request(
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

    async def request_proof(
        self,
        circuit_id: int,
        witness_cid: str,
        *,
        num_partitions: int = 4,
        redundancy: int = 2,
    ) -> dict[str, Any]:
        resp = await self._request(
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

    async def get_proof_job(self, task_id: str) -> dict[str, Any]:
        resp = await self._request("GET", f"{self._url}/proofs/jobs/{task_id}")
        return resp.json()

    async def list_proof_jobs(self, *, status: str | None = None, page: int = 1) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if status:
            params["status"] = status
        resp = await self._request("GET", f"{self._url}/proofs/jobs", params=params)
        return resp.json()

    async def verify_proof(self, proof_id: int, verification_key_cid: str, public_inputs_json: str = "{}") -> dict[str, Any]:
        resp = await self._request(
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

    # ── ZK Provers ───────────────────────────────────────────

    async def list_provers(self, *, online_only: bool = False, page: int = 1) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page}
        if online_only:
            params["online_only"] = "true"
        resp = await self._request("GET", f"{self._url}/provers", params=params)
        return resp.json()

    async def get_network_stats(self) -> dict[str, Any]:
        resp = await self._request("GET", f"{self._url}/provers/stats")
        return resp.json()

    async def get_prover(self, hotkey: str) -> dict[str, Any]:
        resp = await self._request("GET", f"{self._url}/provers/{hotkey}")
        return resp.json()

    async def register_prover(self, **capabilities: Any) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"{self._url}/provers/register",
            params={"hotkey": self._hotkey},
            json=capabilities,
            headers=self._auth_headers(),
        )
        return resp.json()

    async def ping_prover(self, *, vram_available_bytes: int = 0) -> dict[str, Any]:
        resp = await self._request(
            "POST",
            f"{self._url}/provers/ping",
            params={"hotkey": self._hotkey, "vram_available_bytes": vram_available_bytes},
            headers=self._auth_headers(),
        )
        return resp.json()

    # ── ZK Proofs ────────────────────────────────────────────

    async def get_proof(self, proof_id: int) -> dict[str, Any]:
        resp = await self._request("GET", f"{self._url}/proofs/{proof_id}")
        return resp.json()

    async def list_proofs(
        self,
        *,
        circuit_id: int | None = None,
        verified: bool | None = None,
        page: int = 1,
        page_size: int = 20,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if circuit_id is not None:
            params["circuit_id"] = circuit_id
        if verified is not None:
            params["verified"] = str(verified).lower()
        resp = await self._request("GET", f"{self._url}/proofs", params=params)
        return resp.json()

    async def get_job_partitions(self, task_id: str) -> list[dict[str, Any]]:
        resp = await self._request("GET", f"{self._url}/proofs/jobs/{task_id}/partitions")
        return resp.json()

    # ── Organizations ────────────────────────────────────────

    async def list_my_orgs(self) -> list[dict[str, Any]]:
        resp = await self._request(
            "GET", f"{self._url}/orgs/me", headers=self._auth_headers(),
        )
        return resp.json()

    async def get_org(self, slug: str) -> dict[str, Any]:
        resp = await self._request("GET", f"{self._url}/orgs/{slug}")
        return resp.json()

    async def create_org(self, *, name: str, slug: str) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"{self._url}/orgs",
            json={"name": name, "slug": slug},
            headers=self._auth_headers(),
        )
        return resp.json()

    async def list_members(self, slug: str, *, page: int = 1, page_size: int = 20) -> dict[str, Any]:
        resp = await self._request(
            "GET", f"{self._url}/orgs/{slug}/members",
            params={"page": page, "page_size": page_size},
        )
        return resp.json()

    async def add_member(self, slug: str, *, hotkey: str, role: str = "viewer") -> dict[str, Any]:
        resp = await self._request(
            "POST", f"{self._url}/orgs/{slug}/members",
            params={"hotkey": hotkey, "role": role},
            headers=self._auth_headers(),
        )
        return resp.json()

    async def remove_member(self, slug: str, member_hotkey: str) -> None:
        await self._request(
            "DELETE", f"{self._url}/orgs/{slug}/members/{member_hotkey}",
            headers=self._auth_headers(),
        )

    # ── API Keys ─────────────────────────────────────────────

    async def create_api_key(self, *, label: str = "", daily_limit: int = 1000) -> dict[str, Any]:
        resp = await self._request(
            "POST", f"{self._url}/api-keys",
            json={"label": label, "daily_limit": daily_limit},
            headers=self._auth_headers(),
        )
        return resp.json()

    async def list_api_keys(self, *, page: int = 1, page_size: int = 20) -> list[dict[str, Any]]:
        resp = await self._request(
            "GET", f"{self._url}/api-keys",
            params={"page": page, "page_size": page_size},
            headers=self._auth_headers(),
        )
        return resp.json()

    async def revoke_api_key(self, key_id: int) -> None:
        await self._request(
            "DELETE", f"{self._url}/api-keys/{key_id}",
            headers=self._auth_headers(),
        )

    # ── Audit Logs ───────────────────────────────────────────

    async def list_audit_logs(
        self,
        *,
        action: str | None = None,
        resource_type: str | None = None,
        actor_hotkey: str | None = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, Any]:
        params: dict[str, Any] = {"page": page, "page_size": page_size}
        if action:
            params["action"] = action
        if resource_type:
            params["resource_type"] = resource_type
        if actor_hotkey:
            params["actor_hotkey"] = actor_hotkey
        resp = await self._request(
            "GET", f"{self._url}/audit",
            params=params,
            headers=self._auth_headers(),
        )
        return resp.json()

    # ── Streaming downloads ──────────────────────────────────

    async def download_proof(
        self,
        proof_id: int,
        output_path: str | os.PathLike[str],
        *,
        chunk_size: int = 64 * 1024,
    ) -> int:
        """Stream-download proof data to a local file (async)."""
        proof = await self.get_proof(proof_id)
        cid = proof.get("proof_data_cid")
        if not cid:
            raise ModelionnError(f"Proof {proof_id} has no proof_data_cid")

        url = f"{self._url}/proofs/{proof_id}/download"
        client = await self._get_http(timeout=300)
        written = 0
        async with client.stream("GET", url, headers=self._auth_headers()) as stream:
            raise_for_status(stream.status_code, "")
            with open(output_path, "wb") as f:
                async for chunk in stream.aiter_bytes(chunk_size):
                    f.write(chunk)
                    written += len(chunk)
        logger.info("Downloaded proof %d → %s (%d bytes)", proof_id, output_path, written)
        return written

    # ── Batch operations ─────────────────────────────────────

    async def batch_upload_circuits(
        self,
        circuits: list[dict[str, Any]],
        *,
        max_concurrency: int = 5,
    ) -> list[dict[str, Any]]:
        """Upload multiple circuits concurrently with bounded parallelism.

        Each dict must contain keyword arguments for :meth:`upload_circuit`.
        Returns results in the same order; failed items have an ``"error"`` key.
        """
        import asyncio

        sem = asyncio.Semaphore(max_concurrency)

        async def _upload(idx: int, kwargs: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            async with sem:
                try:
                    result = await self.upload_circuit(**kwargs)
                    return idx, result
                except Exception as exc:
                    return idx, {"error": str(exc)}

        tasks = [_upload(i, c) for i, c in enumerate(circuits)]
        raw = await asyncio.gather(*tasks)
        results: list[dict[str, Any] | None] = [None] * len(circuits)
        for idx, result in raw:
            results[idx] = result
        return results  # type: ignore[return-value]

    async def batch_request_proofs(
        self,
        requests: list[dict[str, Any]],
        *,
        max_concurrency: int = 5,
    ) -> list[dict[str, Any]]:
        """Request multiple proof jobs concurrently with bounded parallelism.

        Each dict must contain keyword arguments for :meth:`request_proof`.
        Returns results in the same order.
        """
        import asyncio

        sem = asyncio.Semaphore(max_concurrency)

        async def _request(idx: int, kwargs: dict[str, Any]) -> tuple[int, dict[str, Any]]:
            async with sem:
                try:
                    result = await self.request_proof(**kwargs)
                    return idx, result
                except Exception as exc:
                    return idx, {"error": str(exc)}

        tasks = [_request(i, r) for i, r in enumerate(requests)]
        raw = await asyncio.gather(*tasks)
        results: list[dict[str, Any] | None] = [None] * len(requests)
        for idx, result in raw:
            results[idx] = result
        return results  # type: ignore[return-value]
