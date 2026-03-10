"""Tests for core modules — encryption, security, config, cache."""

from __future__ import annotations

import time
from unittest.mock import patch

import pytest


# ── Encryption ───────────────────────────────────────────────

class TestEncryption:
    def test_round_trip(self):
        from registry.core.encryption import encrypt_field, decrypt_field

        key = "test-master-key-for-encryption"
        plaintext = "sensitive-data-12345"
        ct = encrypt_field(plaintext, key)
        assert ct != plaintext
        assert decrypt_field(ct, key) == plaintext

    def test_different_nonce_each_time(self):
        from registry.core.encryption import encrypt_field

        key = "test-key"
        ct1 = encrypt_field("same", key)
        ct2 = encrypt_field("same", key)
        assert ct1 != ct2  # Different nonces → different ciphertexts

    def test_wrong_key_fails(self):
        from registry.core.encryption import encrypt_field, decrypt_field

        ct = encrypt_field("secret", "key-A")
        with pytest.raises(ValueError, match="Decryption failed"):
            decrypt_field(ct, "key-B")

    def test_tampered_ciphertext_fails(self):
        from registry.core.encryption import encrypt_field, decrypt_field
        import base64

        ct = encrypt_field("secret", "key")
        raw = bytearray(base64.b64decode(ct))
        raw[-1] ^= 0xFF  # Flip a bit
        tampered = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(ValueError):
            decrypt_field(tampered, "key")

    def test_invalid_base64_fails(self):
        from registry.core.encryption import decrypt_field

        with pytest.raises(ValueError):
            decrypt_field("!!!not-base64!!!", "key")

    def test_too_short_payload_fails(self):
        from registry.core.encryption import decrypt_field
        import base64

        short = base64.b64encode(b"\x01" + b"\x00" * 5).decode()
        with pytest.raises(ValueError, match="too short"):
            decrypt_field(short, "key")

    def test_wrong_version_fails(self):
        from registry.core.encryption import encrypt_field, decrypt_field
        import base64

        ct = encrypt_field("test", "key")
        raw = bytearray(base64.b64decode(ct))
        raw[0] = 99  # Bad version
        bad = base64.b64encode(bytes(raw)).decode()
        with pytest.raises(ValueError, match="Unsupported encryption version"):
            decrypt_field(bad, "key")

    def test_bytes_key(self):
        from registry.core.encryption import encrypt_field, decrypt_field

        key = b"binary-master-key-bytes-32-chars!"
        ct = encrypt_field("data", key)
        assert decrypt_field(ct, key) == "data"


# ── Key derivation ───────────────────────────────────────────

class TestKeyDerivation:
    def test_derive_deterministic(self):
        from registry.core.encryption import _derive_key

        k1 = _derive_key("master")
        k2 = _derive_key("master")
        assert k1 == k2

    def test_derive_different_keys(self):
        from registry.core.encryption import _derive_key

        k1 = _derive_key("key-A")
        k2 = _derive_key("key-B")
        assert k1 != k2

    def test_derive_key_length(self):
        from registry.core.encryption import _derive_key

        key = _derive_key("any-master-key")
        assert len(key) == 32  # AES-256


# ── Security: hash_body ──────────────────────────────────────

class TestHashBody:
    def test_hash_body_deterministic(self):
        from registry.core.security import hash_body

        h1 = hash_body(b"payload", "12345")
        h2 = hash_body(b"payload", "12345")
        assert h1 == h2

    def test_hash_body_different_inputs(self):
        from registry.core.security import hash_body

        h1 = hash_body(b"payload-a", "1")
        h2 = hash_body(b"payload-b", "1")
        assert h1 != h2

    def test_hash_body_different_nonces(self):
        from registry.core.security import hash_body

        h1 = hash_body(b"same", "1")
        h2 = hash_body(b"same", "2")
        assert h1 != h2

    def test_hash_body_is_hex(self):
        from registry.core.security import hash_body

        h = hash_body(b"x", "n")
        assert len(h) == 64  # SHA-256 hex = 64 chars
        int(h, 16)  # Should be valid hex


# ── Security: nonce replay prevention ────────────────────────

class TestNonceReplay:
    def test_nonce_first_use_accepted(self):
        from registry.core.security import _check_and_record_nonce, _used_nonces

        _used_nonces.clear()
        assert _check_and_record_nonce("unique-nonce-1", time.time()) is True

    def test_nonce_replay_rejected(self):
        from registry.core.security import _check_and_record_nonce, _used_nonces

        _used_nonces.clear()
        now = time.time()
        _check_and_record_nonce("replay-nonce", now)
        assert _check_and_record_nonce("replay-nonce", now) is False

    def test_expired_nonces_cleaned(self):
        from registry.core.security import _check_and_record_nonce, _used_nonces, _MAX_AGE

        _used_nonces.clear()
        old_time = time.time() - _MAX_AGE - 100
        _used_nonces["old-nonce"] = old_time
        # Recording a new nonce should clean expired ones
        _check_and_record_nonce("new-nonce", time.time())
        assert "old-nonce" not in _used_nonces


# ── Config ───────────────────────────────────────────────────

class TestConfig:
    def test_settings_loaded(self):
        from registry.core.config import settings

        assert settings.api_port == 8000
        assert settings.bt_network in ("finney", "test", "local")
        assert settings.rate_limit_window > 0
        assert settings.max_circuit_constraints > 0

    def test_default_proof_system(self):
        from registry.core.config import settings

        assert settings.default_proof_system == "groth16"
        assert "groth16" in settings.supported_proof_systems

    def test_partition_settings(self):
        from registry.core.config import settings

        assert settings.partition_redundancy >= 1
        assert settings.max_partitions_per_job >= 1
        assert settings.max_constraints_per_partition > 0


# ── Database models ──────────────────────────────────────────

class TestDatabaseModels:
    def test_proof_type_enum(self):
        from registry.models.database import ProofType

        assert ProofType.GROTH16.value == "groth16"
        assert ProofType.PLONK.value == "plonk"
        assert ProofType.HALO2.value == "halo2"
        assert ProofType.STARK.value == "stark"

    def test_circuit_category_enum(self):
        from registry.models.database import CircuitCategory

        assert CircuitCategory.GENERAL.value == "general"
        assert CircuitCategory.EVM.value == "evm"
        assert CircuitCategory.ZKML.value == "zkml"
        assert CircuitCategory.CUSTOM.value == "custom"

    def test_proof_job_status_enum(self):
        from registry.models.database import ProofJobStatus

        values = {s.value for s in ProofJobStatus}
        assert "queued" in values
        assert "proving" in values
        assert "completed" in values
        assert "failed" in values
        assert "timeout" in values

    def test_gpu_backend_enum(self):
        from registry.models.database import GpuBackendEnum

        values = {g.value for g in GpuBackendEnum}
        assert {"cuda", "rocm", "metal", "webgpu", "cpu"} == values

    def test_audit_action_enum(self):
        from registry.models.database import AuditAction

        assert AuditAction.CIRCUIT_UPLOADED.value == "circuit.uploaded"
        assert AuditAction.PROOF_REQUESTED.value == "proof.requested"

    def test_org_role_enum(self):
        from registry.models.database import OrgRole

        assert OrgRole.ADMIN.value == "admin"
        assert OrgRole.EDITOR.value == "editor"
        assert OrgRole.VIEWER.value == "viewer"


# ── SDK errors ───────────────────────────────────────────────

class TestSDKErrors:
    def test_rate_limit_error_retry_after(self):
        from sdk.errors import RateLimitError

        err = RateLimitError(retry_after=30)
        assert err.retry_after == 30
        assert err.status_code == 429

    def test_modelionn_error_status_code(self):
        from sdk.errors import ModelionnError

        err = ModelionnError("test", status_code=418, detail="teapot")
        assert err.status_code == 418
        assert err.detail == "teapot"
        assert str(err) == "test"
