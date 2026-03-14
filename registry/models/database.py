"""SQLAlchemy ORM models for the metadata store."""

from __future__ import annotations

import enum
from datetime import datetime, timezone

from sqlalchemy import Boolean, DateTime, Enum, Float, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


class Base(DeclarativeBase):
    pass


# ── RBAC Enums ──────────────────────────────────────────────

class OrgRole(str, enum.Enum):
    VIEWER = "viewer"
    EDITOR = "editor"
    ADMIN = "admin"


class AuditAction(str, enum.Enum):
    USER_LOGIN = "user.login"
    API_KEY_CREATED = "api_key.created"
    API_KEY_REVOKED = "api_key.revoked"
    ORG_CREATED = "org.created"
    ORG_UPDATED = "org.updated"
    MEMBER_ADDED = "member.added"
    MEMBER_REMOVED = "member.removed"
    MEMBER_ROLE_CHANGED = "member.role_changed"
    SETTINGS_CHANGED = "settings.changed"
    CIRCUIT_UPLOADED = "circuit.uploaded"
    PROOF_REQUESTED = "proof.requested"
    PROOF_COMPLETED = "proof.completed"
    PROOF_FAILED = "proof.failed"
    PROVER_REGISTERED = "prover.registered"


# ── ZK Proof Enums ──────────────────────────────────────────

class ProofType(str, enum.Enum):
    GROTH16 = "groth16"
    PLONK = "plonk"
    HALO2 = "halo2"
    STARK = "stark"


class CircuitCategory(str, enum.Enum):
    GENERAL = "general"
    EVM = "evm"
    ZKML = "zkml"
    CUSTOM = "custom"


class ProofJobStatus(str, enum.Enum):
    QUEUED = "queued"
    PARTITIONING = "partitioning"
    DISPATCHED = "dispatched"
    PROVING = "proving"
    AGGREGATING = "aggregating"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"


# Valid state transitions for proof jobs
VALID_TRANSITIONS: dict[ProofJobStatus, set[ProofJobStatus]] = {
    ProofJobStatus.QUEUED: {ProofJobStatus.PARTITIONING, ProofJobStatus.DISPATCHED, ProofJobStatus.CANCELLED, ProofJobStatus.FAILED},
    ProofJobStatus.PARTITIONING: {ProofJobStatus.DISPATCHED, ProofJobStatus.FAILED},
    ProofJobStatus.DISPATCHED: {ProofJobStatus.PROVING, ProofJobStatus.CANCELLED, ProofJobStatus.FAILED},
    ProofJobStatus.PROVING: {ProofJobStatus.AGGREGATING, ProofJobStatus.TIMEOUT, ProofJobStatus.CANCELLED, ProofJobStatus.FAILED},
    ProofJobStatus.AGGREGATING: {ProofJobStatus.VERIFYING, ProofJobStatus.FAILED},
    ProofJobStatus.VERIFYING: {ProofJobStatus.COMPLETED, ProofJobStatus.FAILED},
    ProofJobStatus.COMPLETED: set(),
    ProofJobStatus.FAILED: set(),
    ProofJobStatus.TIMEOUT: set(),
    ProofJobStatus.CANCELLED: set(),
}


def validate_status_transition(current: ProofJobStatus | str, target: ProofJobStatus | str) -> bool:
    """Check if a status transition is valid. Returns True if allowed."""
    if isinstance(current, str):
        current = ProofJobStatus(current)
    if isinstance(target, str):
        target = ProofJobStatus(target)
    return target in VALID_TRANSITIONS.get(current, set())


class GpuBackendEnum(str, enum.Enum):
    CUDA = "cuda"
    ROCM = "rocm"
    METAL = "metal"
    WEBGPU = "webgpu"
    CPU = "cpu"


# ── Multi-Tenancy Models ────────────────────────────────────

class OrganizationRow(Base):
    """Organization / tenant — all resources are scoped to an org."""

    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    slug: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    settings_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class UserRow(Base):
    """Registered user — linked to Bittensor hotkey."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hotkey: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(128), default="")
    email: Mapped[str | None] = mapped_column(String(256), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )


class MembershipRow(Base):
    """User ↔ Organization membership with role."""

    __tablename__ = "memberships"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id"), nullable=False, index=True)
    org_id: Mapped[int] = mapped_column(Integer, ForeignKey("organizations.id"), nullable=False, index=True)
    role: Mapped[str] = mapped_column(Enum(OrgRole), nullable=False, default=OrgRole.VIEWER)

    user: Mapped["UserRow"] = relationship("UserRow", lazy="selectin")
    organization: Mapped["OrganizationRow"] = relationship("OrganizationRow", lazy="selectin")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_membership_user_org", "user_id", "org_id", unique=True),
    )


# ── Audit Trail ─────────────────────────────────────────────

class AuditLogRow(Base):
    """Immutable audit log entry — append-only."""

    __tablename__ = "audit_logs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    org_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    actor_hotkey: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    action: Mapped[str] = mapped_column(Enum(AuditAction), nullable=False, index=True)
    resource_type: Mapped[str] = mapped_column(String(64), nullable=False)
    resource_id: Mapped[str] = mapped_column(String(256), nullable=False)
    old_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    new_value: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_audit_org_created", "org_id", "created_at"),
        Index("ix_audit_resource", "resource_type", "resource_id"),
    )


class APIKeyRow(Base):
    """API key for rate-limited access."""

    __tablename__ = "api_keys"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    hotkey: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    label: Mapped[str] = mapped_column(String(128), default="")
    requests_today: Mapped[int] = mapped_column(Integer, default=0)
    daily_limit: Mapped[int] = mapped_column(Integer, default=1000)
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    last_used_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


# ── ZK Circuit Registry ─────────────────────────────────────

class CircuitRow(Base):
    """Registered ZK circuit — compiled constraint system ready for proving."""

    __tablename__ = "circuits"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    circuit_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    version: Mapped[str] = mapped_column(String(64), nullable=False, default="1.0.0")
    description: Mapped[str] = mapped_column(Text, default="")
    proof_type: Mapped[str] = mapped_column(Enum(ProofType), nullable=False, index=True)
    circuit_type: Mapped[str] = mapped_column(Enum(CircuitCategory), nullable=False, default=CircuitCategory.GENERAL)
    num_constraints: Mapped[int] = mapped_column(Integer, nullable=False)
    num_public_inputs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    num_private_inputs: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    ipfs_cid: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    proving_key_cid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verification_key_cid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    publisher_hotkey: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    org_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("organizations.id", ondelete="SET NULL"), nullable=True, index=True)
    downloads: Mapped[int] = mapped_column(Integer, default=0)
    proofs_generated: Mapped[int] = mapped_column(Integer, default=0)
    tags_csv: Mapped[str] = mapped_column(Text, default="")
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_circuit_name_version", "name", "version", unique=True),
        Index("ix_circuit_proof_type", "proof_type"),
        Index("ix_circuit_created", "created_at"),
    )


class ProofRow(Base):
    """Generated ZK proof — stored with verification metadata."""

    __tablename__ = "proofs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    proof_hash: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    circuit_id: Mapped[int] = mapped_column(Integer, ForeignKey("circuits.id"), nullable=False, index=True)
    job_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("proof_jobs.id"), nullable=True, index=True)
    proof_type: Mapped[str] = mapped_column(Enum(ProofType), nullable=False)
    format_version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    proof_data_cid: Mapped[str] = mapped_column(String(128), nullable=False)
    public_inputs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    proof_size_bytes: Mapped[int] = mapped_column(Integer, default=0)
    generation_time_ms: Mapped[int] = mapped_column(Integer, default=0)
    gpu_backend: Mapped[str | None] = mapped_column(Enum(GpuBackendEnum), nullable=True)
    prover_hotkey: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    verified: Mapped[bool] = mapped_column(default=False)
    verified_by: Mapped[str | None] = mapped_column(String(128), nullable=True)
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ipfs_cid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    circuit: Mapped["CircuitRow"] = relationship("CircuitRow", lazy="selectin")

    __table_args__ = (
        Index("ix_proof_circuit_created", "circuit_id", "created_at"),
    )


class ProofJobRow(Base):
    """Async proof generation job — tracks distributed proof pipeline state."""

    __tablename__ = "proof_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[str] = mapped_column(String(64), nullable=False, unique=True, index=True)
    circuit_id: Mapped[int] = mapped_column(Integer, ForeignKey("circuits.id"), nullable=False, index=True)
    requester_hotkey: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    status: Mapped[str] = mapped_column(
        Enum(ProofJobStatus), nullable=False, default=ProofJobStatus.QUEUED, index=True
    )
    num_partitions: Mapped[int] = mapped_column(Integer, default=1)
    partitions_completed: Mapped[int] = mapped_column(Integer, default=0)
    redundancy: Mapped[int] = mapped_column(Integer, default=2)
    witness_cid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    public_inputs_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    result_proof_id: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    estimated_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    actual_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_backend_used: Mapped[str | None] = mapped_column(Enum(GpuBackendEnum), nullable=True)
    config_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    circuit: Mapped["CircuitRow"] = relationship("CircuitRow", lazy="selectin")

    __table_args__ = (
        Index("ix_proof_job_status_created", "status", "created_at"),
    )


class ProverCapabilityRow(Base):
    """Registered prover (miner) GPU capabilities and health tracking."""

    __tablename__ = "prover_capabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hotkey: Mapped[str] = mapped_column(String(128), nullable=False, unique=True, index=True)
    gpu_name: Mapped[str] = mapped_column(String(256), default="")
    gpu_backend: Mapped[str] = mapped_column(Enum(GpuBackendEnum), nullable=False, default=GpuBackendEnum.CPU)
    gpu_count: Mapped[int] = mapped_column(Integer, default=1)
    vram_total_bytes: Mapped[int] = mapped_column(Integer, default=0)
    vram_available_bytes: Mapped[int] = mapped_column(Integer, default=0)
    compute_units: Mapped[int] = mapped_column(Integer, default=0)
    compute_version: Mapped[str] = mapped_column(String(32), default="")
    benchmark_score: Mapped[float] = mapped_column(Float, default=0.0)
    supported_proof_types_csv: Mapped[str] = mapped_column(Text, default="groth16,plonk,halo2,stark")
    max_constraints: Mapped[int] = mapped_column(Integer, default=0)
    total_proofs: Mapped[int] = mapped_column(Integer, default=0)
    successful_proofs: Mapped[int] = mapped_column(Integer, default=0)
    failed_proofs: Mapped[int] = mapped_column(Integer, default=0)
    avg_proof_time_ms: Mapped[float] = mapped_column(Float, default=0.0)
    uptime_ratio: Mapped[float] = mapped_column(Float, default=1.0)
    last_ping_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    online: Mapped[bool] = mapped_column(default=False, index=True)
    stake: Mapped[float] = mapped_column(Float, default=0.0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )

    __table_args__ = (
        Index("ix_prover_benchmark", "benchmark_score"),
        Index("ix_prover_online_gpu", "online", "gpu_backend"),
    )


class CircuitPartitionRow(Base):
    """Tracks partition assignment and completion for a proof job."""

    __tablename__ = "circuit_partitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    job_id: Mapped[int] = mapped_column(Integer, ForeignKey("proof_jobs.id"), nullable=False, index=True)
    partition_index: Mapped[int] = mapped_column(Integer, nullable=False)
    total_partitions: Mapped[int] = mapped_column(Integer, nullable=False)
    constraint_start: Mapped[int] = mapped_column(Integer, nullable=False)
    constraint_end: Mapped[int] = mapped_column(Integer, nullable=False)
    assigned_prover: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    status: Mapped[str] = mapped_column(
        String(32), nullable=False, default="pending"  # pending | assigned | proving | completed | failed
    )
    proof_fragment_cid: Mapped[str | None] = mapped_column(String(128), nullable=True)
    generation_time_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    gpu_backend_used: Mapped[str | None] = mapped_column(Enum(GpuBackendEnum), nullable=True)
    assigned_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)

    __table_args__ = (
        Index("ix_partition_job_index", "job_id", "partition_index", unique=True),
    )


# ── Webhook Configuration ───────────────────────────────────

class WebhookEventType(str, enum.Enum):
    PROOF_COMPLETED = "proof.completed"
    PROOF_FAILED = "proof.failed"
    CIRCUIT_UPLOADED = "circuit.uploaded"
    PROVER_ONLINE = "prover.online"
    PROVER_OFFLINE = "prover.offline"


class WebhookConfigRow(Base):
    """User-configured webhook endpoint for event notifications."""

    __tablename__ = "webhook_configs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    hotkey: Mapped[str] = mapped_column(String(128), nullable=False, index=True)
    url: Mapped[str] = mapped_column(String(2048), nullable=False)
    label: Mapped[str] = mapped_column(String(128), default="")
    events: Mapped[str] = mapped_column(Text, nullable=False, default="*")
    secret: Mapped[str] = mapped_column(String(64), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        server_default=func.now(),
    )
    last_triggered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        Index("ix_webhook_hotkey_active", "hotkey", "active"),
    )
