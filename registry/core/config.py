"""Modelionn application settings."""

from __future__ import annotations

from pathlib import Path
from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="MODELIONN_", env_file=".env")

    # --- API ---
    api_host: str = "0.0.0.0"
    api_port: int = 8000
    debug: bool = False
    secret_key: str = "change-me-in-production-use-64-chars-minimum-random-string!!"

    # --- Database ---
    database_url: str = "sqlite+aiosqlite:///./data/modelionn.db"

    # --- IPFS ---
    ipfs_api_url: str = "http://127.0.0.1:5001"
    ipfs_gateway_url: str = "http://127.0.0.1:8080"
    ipfs_chunk_size: int = 256 * 1024  # 256 KB chunks for large uploads

    # --- Validation ---
    max_task_id_len: int = 256
    max_hotkey_len: int = 128

    # --- Bittensor ---
    bt_network: Literal["finney", "test", "local"] = "test"
    bt_netuid: int = 1
    bt_wallet_name: str = "default"
    bt_wallet_hotkey: str = "default"
    min_stake_to_publish: float = 0.0  # TAO — 0 for testnet

    # --- Storage ---
    cache_dir: Path = Path.home() / ".modelionn" / "cache"
    data_dir: Path = Path("./data")

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- Celery ---
    celery_broker_url: str = "redis://localhost:6379/1"
    celery_result_backend: str = "redis://localhost:6379/2"

    # --- CORS ---
    cors_origins: str = "http://localhost:3000"  # comma-separated origins

    # --- Rate Limiting ---
    rate_limit_window: int = 60  # seconds
    rate_limit_max: int = 120  # requests per window

    # --- Security ---
    require_signature_verification: bool = False  # Set True in production

    # --- ZK Prover ---
    prover_timeout_s: int = 600  # Max time for a single proof job
    max_circuit_constraints: int = 1_000_000_000  # 1B constraint limit
    max_circuit_size_bytes: int = 10 * 1024 * 1024 * 1024  # 10 GB
    partition_redundancy: int = 2  # Each partition assigned to N provers
    max_partitions_per_job: int = 256
    max_constraints_per_partition: int = 10_000_000
    gpu_memory_limit_bytes: int = 0  # 0 = no limit (auto-detect)
    prover_health_interval_s: int = 60  # How often to ping provers
    prover_benchmark_interval_s: int = 21600  # 6 hours
    prover_offline_threshold_s: int = 180  # Mark offline after 3 missed pings
    proof_result_ttl_s: int = 86400  # 24 hours
    supported_proof_systems: str = "groth16,plonk,halo2,stark"
    default_proof_system: str = "groth16"


_DEFAULT_SECRET = "change-me-in-production-use-64-chars-minimum-random-string!!"
settings = Settings()

if settings.secret_key == _DEFAULT_SECRET:
    if not settings.debug:
        raise RuntimeError(
            "MODELIONN_SECRET_KEY is still the default value. "
            "Set a strong random secret before running in production mode (debug=False)."
        )
    import logging as _logging
    _logging.getLogger(__name__).warning(
        "MODELIONN_SECRET_KEY is the default value. "
        "Set MODELIONN_SECRET_KEY to a strong random secret before deploying."
    )

# Enforce signature verification in non-debug mode
if not settings.debug and not settings.require_signature_verification:
    raise RuntimeError(
        "MODELIONN_REQUIRE_SIGNATURE_VERIFICATION must be True in production mode "
        "(debug=False). Set MODELIONN_REQUIRE_SIGNATURE_VERIFICATION=true before deploying."
    )
