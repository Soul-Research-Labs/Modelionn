"""Tests for IPFS storage backend — upload, download, integrity check, and error handling."""

from __future__ import annotations

import hashlib
import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from registry.storage.base import UploadResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


_SAMPLE_DATA = b"hello world from the ZK prover"
_SAMPLE_CID = "QmTestCid123"
_SAMPLE_HASH = _sha256(_SAMPLE_DATA)


def _mock_add_response(cid: str = _SAMPLE_CID, size: int | None = None):
    """Return an httpx.Response that mimics IPFS /api/v0/add."""
    body = {"Hash": cid, "Size": str(size or len(_SAMPLE_DATA))}
    return httpx.Response(200, json=body)


def _mock_cat_response(data: bytes = _SAMPLE_DATA):
    """Return an httpx.Response that mimics IPFS /api/v0/cat."""
    return httpx.Response(200, content=data)


# ---------------------------------------------------------------------------
# Upload
# ---------------------------------------------------------------------------

class TestIPFSUpload:
    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        """Avoid hitting real IPFS during tests."""
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_api_url", "http://fakeipfs:5001")
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_chunk_size", 262144)

    async def test_upload_roundtrip(self):
        """Upload data, verify CID + hash returned, content verified."""
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")

        mock_post = AsyncMock(side_effect=[
            _mock_add_response(),    # upload
            _mock_cat_response(),    # verification download
        ])
        with patch("httpx.AsyncClient.post", mock_post):
            result = await storage.upload(_SAMPLE_DATA, filename="test.bin")

        assert isinstance(result, UploadResult)
        assert result.cid == _SAMPLE_CID
        assert result.sha256_hash == _SAMPLE_HASH
        assert result.size_bytes == len(_SAMPLE_DATA)
        assert mock_post.call_count == 2

    async def test_upload_hash_mismatch_raises(self):
        """If re-downloaded data doesn't match, upload should raise ValueError."""
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")

        mock_post = AsyncMock(side_effect=[
            _mock_add_response(),           # upload succeeds
            _mock_cat_response(b"corrupt"), # verification fails
            _mock_cat_response(b"corrupt"), # retry 2
            _mock_cat_response(b"corrupt"), # retry 3
        ])

        with patch("httpx.AsyncClient.post", mock_post):
            with pytest.raises(ValueError, match="hash mismatch"):
                await storage.upload(_SAMPLE_DATA)


# ---------------------------------------------------------------------------
# Download
# ---------------------------------------------------------------------------

class TestIPFSDownload:
    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_api_url", "http://fakeipfs:5001")
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_chunk_size", 262144)

    async def test_download_returns_bytes(self):
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")
        mock_post = AsyncMock(return_value=_mock_cat_response())

        with patch("httpx.AsyncClient.post", mock_post):
            data = await storage.download(_SAMPLE_CID)

        assert data == _SAMPLE_DATA

    async def test_download_to_path_writes_file(self, tmp_path):
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")
        dest = str(tmp_path / "output.bin")
        mock_post = AsyncMock(return_value=_mock_cat_response())

        with patch("httpx.AsyncClient.post", mock_post):
            await storage.download_to_path(_SAMPLE_CID, dest)

        assert Path(dest).read_bytes() == _SAMPLE_DATA


# ---------------------------------------------------------------------------
# Upload path
# ---------------------------------------------------------------------------

class TestIPFSUploadPath:
    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_api_url", "http://fakeipfs:5001")
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_chunk_size", 262144)

    async def test_upload_path_single_file(self, tmp_path):
        """Upload a single file via upload_path delegates to upload()."""
        from registry.storage.ipfs import IPFSStorage

        file = tmp_path / "circuit.r1cs"
        file.write_bytes(_SAMPLE_DATA)

        storage = IPFSStorage("http://fakeipfs:5001")
        mock_post = AsyncMock(side_effect=[
            _mock_add_response(),
            _mock_cat_response(),
        ])

        with patch("httpx.AsyncClient.post", mock_post):
            result = await storage.upload_path(str(file))

        assert result.cid == _SAMPLE_CID

    async def test_upload_path_nonexistent_raises(self):
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")
        with pytest.raises(FileNotFoundError):
            await storage.upload_path("/nonexistent/path/file.bin")


# ---------------------------------------------------------------------------
# Pin / Unpin / Exists
# ---------------------------------------------------------------------------

class TestIPFSPinAndExists:
    @pytest.fixture(autouse=True)
    def _patch_settings(self, monkeypatch):
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_api_url", "http://fakeipfs:5001")
        monkeypatch.setattr("registry.storage.ipfs.settings.ipfs_chunk_size", 262144)

    async def test_pin(self):
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")
        mock_post = AsyncMock(return_value=httpx.Response(200, json={"Pins": [_SAMPLE_CID]}))

        with patch("httpx.AsyncClient.post", mock_post):
            await storage.pin(_SAMPLE_CID)

        assert mock_post.called
        call_args = mock_post.call_args
        assert "pin/add" in str(call_args)

    async def test_exists_returns_true(self):
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")
        mock_post = AsyncMock(return_value=httpx.Response(200, json={"Hash": _SAMPLE_CID}))

        with patch("httpx.AsyncClient.post", mock_post):
            assert await storage.exists(_SAMPLE_CID) is True

    async def test_exists_returns_false_on_error(self):
        from registry.storage.ipfs import IPFSStorage

        storage = IPFSStorage("http://fakeipfs:5001")
        mock_post = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

        with patch("httpx.AsyncClient.post", mock_post):
            assert await storage.exists(_SAMPLE_CID) is False
