"""Tests for the miner neuron — CID validation, capability state, download limits."""

from __future__ import annotations

import re
import sys
from unittest.mock import MagicMock

import pytest

# Mock bittensor before importing miner module
if "bittensor" not in sys.modules:
    _bt = MagicMock()
    _bt.Synapse = type("Synapse", (), {})
    _bt.config = MagicMock()
    _bt.axon = MagicMock()
    sys.modules["bittensor"] = _bt

from subnet.neurons.miner import _CID_RE, _MAX_IPFS_DOWNLOAD_BYTES


# ── CID validation ──────────────────────────────────────────

class TestCIDValidation:
    """Ensure the CID regex accepts valid CIDv0/v1 and rejects garbage."""

    VALID_CIDv0 = [
        "QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",
        "QmT5NvUtoM5nWFfrQnVFwHvBpiFkHjbGEhYbTnTEt5aYrj",
        "QmUNLLsPACCz1vLxQVkXqqLX5R1X345qqfHbsf67hvA3Nn",
    ]

    VALID_CIDv1 = [
        "bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi",
    ]

    INVALID = [
        "",
        "not-a-cid",
        "Qm",  # too short
        "QmTooShort",
        "bafyinvalid!!chars",
        "ipfs://QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",  # protocol prefix
        " QmYwAPJzv5CZsnA625s3Xf2nemtYgPpHdWEz79ojWnPbdG",  # leading space
    ]

    @pytest.mark.parametrize("cid", VALID_CIDv0 + VALID_CIDv1)
    def test_valid_cid_accepted(self, cid: str):
        assert _CID_RE.match(cid), f"Should accept: {cid}"

    @pytest.mark.parametrize("cid", INVALID)
    def test_invalid_cid_rejected(self, cid: str):
        assert not _CID_RE.match(cid), f"Should reject: {cid}"


# ── Download limits ─────────────────────────────────────────

class TestDownloadLimits:
    def test_max_download_bytes_is_256mb(self):
        assert _MAX_IPFS_DOWNLOAD_BYTES == 256 * 1024 * 1024

    def test_limit_is_int(self):
        assert isinstance(_MAX_IPFS_DOWNLOAD_BYTES, int)


# ── Miner construction (no GPU required) ────────────────────

class TestMinerInit:
    """Test the miner class can be imported and constants are sane."""

    def test_cid_regex_is_compiled(self):
        assert isinstance(_CID_RE, re.Pattern)

    def test_cid_regex_anchored(self):
        """Regex must be anchored to prevent prefix-only matches."""
        assert _CID_RE.pattern.startswith("^")
        assert _CID_RE.pattern.endswith("$")
