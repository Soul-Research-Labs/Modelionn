"""Modelionn Python SDK — ZK prover network client."""

from __future__ import annotations

import hashlib
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
            env = os.environ.get("MODELIONN_ENV", "development")
            if env == "production":
                raise ModelionnError(
                    "sign_fn is required in production. "
                    "Provide a real signer or set MODELIONN_ENV=development."
                )
            # Dev fallback: sha256 of message (not secure — use real signer in prod)
            sig = hashlib.sha256(message.encode()).hexdigest()
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
