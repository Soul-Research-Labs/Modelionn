"""Abstract storage backend interface."""

from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class UploadResult:
    cid: str
    size_bytes: int
    sha256_hash: str


class StorageBackend(abc.ABC):
    """Interface every storage adapter must implement."""

    @abc.abstractmethod
    async def upload(self, data: bytes, *, filename: str = "") -> UploadResult:
        """Upload raw bytes and return the content identifier."""

    @abc.abstractmethod
    async def upload_path(self, path: str) -> UploadResult:
        """Upload a file or directory from local filesystem."""

    @abc.abstractmethod
    async def download(self, cid: str) -> bytes:
        """Download the full content addressed by *cid*."""

    @abc.abstractmethod
    async def download_to_path(self, cid: str, dest: str) -> None:
        """Download content to a local path."""

    @abc.abstractmethod
    async def pin(self, cid: str) -> None:
        """Ensure the content remains available on the storage network."""

    @abc.abstractmethod
    async def unpin(self, cid: str) -> None:
        """Allow the content to be garbage-collected."""

    @abc.abstractmethod
    async def exists(self, cid: str) -> bool:
        """Return True if the CID is accessible."""
