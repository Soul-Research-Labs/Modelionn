"""IPFS storage adapter — implements StorageBackend using a Kubo (go-ipfs) node."""

from __future__ import annotations

import hashlib
import logging
import os
from pathlib import Path

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from registry.core.config import settings
from registry.storage.base import StorageBackend, UploadResult

logger = logging.getLogger(__name__)

_CHUNK = settings.ipfs_chunk_size  # 256 KB default

_RETRY = retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.ConnectError, httpx.TimeoutException)),
    reraise=True,
)


class IPFSStorage(StorageBackend):
    """Talks to the IPFS Kubo HTTP API (default :5001)."""

    def __init__(self, api_url: str | None = None) -> None:
        self._api = (api_url or settings.ipfs_api_url).rstrip("/")

    # ── helpers ──────────────────────────────────────────────

    def _url(self, endpoint: str) -> str:
        return f"{self._api}/api/v0/{endpoint.lstrip('/')}"

    @staticmethod
    def _sha256(data: bytes) -> str:
        return hashlib.sha256(data).hexdigest()

    # ── public interface ─────────────────────────────────────

    @_RETRY
    async def upload(self, data: bytes, *, filename: str = "") -> UploadResult:
        sha = self._sha256(data)
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(
                self._url("add"),
                files={"file": (filename or "blob", data)},
                params={"pin": "true", "quieter": "true"},
            )
            resp.raise_for_status()
            body = resp.json()
        cid = body["Hash"]
        size = int(body.get("Size", len(data)))

        # Verify content integrity after upload
        downloaded = await self.download(cid)
        if self._sha256(downloaded) != sha:
            raise ValueError(f"IPFS content verification failed for CID {cid}: hash mismatch")

        logger.info("Uploaded %s  cid=%s  size=%d  (verified)", filename, cid, size)
        return UploadResult(cid=cid, size_bytes=size, sha256_hash=sha)

    async def upload_path(self, path: str) -> UploadResult:
        p = Path(path)
        if not p.exists():
            raise FileNotFoundError(path)
        if p.is_file():
            data = p.read_bytes()
            return await self.upload(data, filename=p.name)
        # Directory: tar the whole thing and add recursively
        files: list[tuple[str, tuple[str, bytes]]] = []
        sha = hashlib.sha256()
        total_size = 0
        for root, _dirs, fnames in os.walk(p):
            for fn in fnames:
                fp = Path(root) / fn
                content = fp.read_bytes()
                sha.update(content)
                total_size += len(content)
                rel = str(fp.relative_to(p))
                files.append(("file", (rel, content)))
        async with httpx.AsyncClient(timeout=600) as client:
            resp = await client.post(
                self._url("add"),
                files=files,
                params={"pin": "true", "wrap-with-directory": "true", "quieter": "true"},
            )
            resp.raise_for_status()
            # last line is the wrapper directory
            lines = resp.text.strip().splitlines()
            import json
            body = json.loads(lines[-1])
        return UploadResult(cid=body["Hash"], size_bytes=total_size, sha256_hash=sha.hexdigest())

    @_RETRY
    async def download(self, cid: str) -> bytes:
        async with httpx.AsyncClient(timeout=300) as client:
            resp = await client.post(self._url("cat"), params={"arg": cid})
            resp.raise_for_status()
            return resp.content

    async def download_to_path(self, cid: str, dest: str) -> None:
        data = await self.download(cid)
        dp = Path(dest)
        dp.parent.mkdir(parents=True, exist_ok=True)
        dp.write_bytes(data)

    @_RETRY
    async def pin(self, cid: str) -> None:
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(self._url("pin/add"), params={"arg": cid})
            resp.raise_for_status()

    async def unpin(self, cid: str) -> None:
        async with httpx.AsyncClient(timeout=60) as client:
            resp = await client.post(self._url("pin/rm"), params={"arg": cid})
            resp.raise_for_status()

    async def exists(self, cid: str) -> bool:
        try:
            async with httpx.AsyncClient(timeout=15) as client:
                resp = await client.post(self._url("object/stat"), params={"arg": cid})
                return resp.status_code == 200
        except httpx.HTTPError:
            return False
