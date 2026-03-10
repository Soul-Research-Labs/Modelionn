"""drop legacy tables, add ZK prover tables

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-10

Removes all legacy AI artifact registry tables and adds the ZK prover
network tables (circuits, proofs, proof_jobs, prover_capabilities,
circuit_partitions).
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Drop legacy tables (reverse dependency order) ────────
    for table in [
        "webhook_deliveries",
        "notification_configs",
        "webhook_configs",
        "validator_states",
        "eval_jobs",
        "commit_reveals",
        "vulnerability_reports",
        "bounties",
        "benchmark_scores",
        "model_cards",
        "publisher_reputation",
        "artifact_tags",
        "artifacts",
    ]:
        op.drop_table(table)

    # Also drop indexes from migration 0002 that referenced artifacts
    # (these are already gone since the table is dropped)

    # ── ZK Prover tables ─────────────────────────────────────

    op.create_table(
        "circuits",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), server_default="1.0.0"),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("proof_type", sa.String(32), nullable=False),
        sa.Column("circuit_type", sa.String(32), nullable=False),
        sa.Column("num_constraints", sa.Integer, nullable=False),
        sa.Column("num_public_inputs", sa.Integer, server_default="0"),
        sa.Column("num_private_inputs", sa.Integer, server_default="0"),
        sa.Column("ipfs_cid", sa.String(128), nullable=False, unique=True),
        sa.Column("verification_key_cid", sa.String(128), nullable=True),
        sa.Column("sha256_hash", sa.String(64), nullable=True),
        sa.Column("size_bytes", sa.Integer, server_default="0"),
        sa.Column("publisher_hotkey", sa.String(128), nullable=False),
        sa.Column("org_id", sa.Integer, nullable=True),
        sa.Column("downloads", sa.Integer, server_default="0"),
        sa.Column("tags_csv", sa.Text, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_circuits_proof_type", "circuits", ["proof_type"])
    op.create_index("ix_circuits_circuit_type", "circuits", ["circuit_type"])
    op.create_index("ix_circuits_publisher_hotkey", "circuits", ["publisher_hotkey"])
    op.create_index("ix_circuits_ipfs_cid", "circuits", ["ipfs_cid"])

    op.create_table(
        "proof_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(64), nullable=False, unique=True),
        sa.Column("circuit_id", sa.Integer, sa.ForeignKey("circuits.id"), nullable=False),
        sa.Column("witness_cid", sa.String(128), nullable=False),
        sa.Column("proof_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("requester_hotkey", sa.String(128), nullable=False),
        sa.Column("num_partitions", sa.Integer, server_default="1"),
        sa.Column("redundancy_factor", sa.Integer, server_default="2"),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_proof_jobs_task_id", "proof_jobs", ["task_id"])
    op.create_index("ix_proof_jobs_status", "proof_jobs", ["status"])
    op.create_index("ix_proof_jobs_circuit_id", "proof_jobs", ["circuit_id"])
    op.create_index("ix_proof_jobs_requester_hotkey", "proof_jobs", ["requester_hotkey"])

    op.create_table(
        "circuit_partitions",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("proof_jobs.id"), nullable=False),
        sa.Column("partition_index", sa.Integer, nullable=False),
        sa.Column("constraint_start", sa.Integer, nullable=False),
        sa.Column("constraint_end", sa.Integer, nullable=False),
        sa.Column("assigned_hotkey", sa.String(128), nullable=True),
        sa.Column("status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("proof_cid", sa.String(128), nullable=True),
        sa.Column("generation_time_s", sa.Float, nullable=True),
        sa.Column("verified", sa.Boolean, server_default="0"),
        sa.Column("verifier_hotkey", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_circuit_partitions_job_id", "circuit_partitions", ["job_id"])
    op.create_index("ix_circuit_partitions_assigned_hotkey", "circuit_partitions", ["assigned_hotkey"])

    op.create_table(
        "proofs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("job_id", sa.Integer, sa.ForeignKey("proof_jobs.id"), nullable=False),
        sa.Column("circuit_id", sa.Integer, sa.ForeignKey("circuits.id"), nullable=False),
        sa.Column("proof_cid", sa.String(128), nullable=False),
        sa.Column("proof_type", sa.String(32), nullable=False),
        sa.Column("generation_time_s", sa.Float, nullable=True),
        sa.Column("proof_size_bytes", sa.Integer, nullable=True),
        sa.Column("verified", sa.Boolean, server_default="0"),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("verifier_hotkey", sa.String(128), nullable=True),
        sa.Column("prover_hotkey", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_proofs_job_id", "proofs", ["job_id"])
    op.create_index("ix_proofs_circuit_id", "proofs", ["circuit_id"])
    op.create_index("ix_proofs_proof_cid", "proofs", ["proof_cid"])

    op.create_table(
        "prover_capabilities",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("hotkey", sa.String(128), nullable=False, unique=True),
        sa.Column("gpu_name", sa.String(128), nullable=True),
        sa.Column("gpu_backend", sa.String(32), nullable=True),
        sa.Column("gpu_vram_bytes", sa.Integer, server_default="0"),
        sa.Column("supported_proof_types", sa.Text, server_default=""),
        sa.Column("benchmark_score", sa.Float, server_default="0.0"),
        sa.Column("total_proofs", sa.Integer, server_default="0"),
        sa.Column("successful_proofs", sa.Integer, server_default="0"),
        sa.Column("failed_proofs", sa.Integer, server_default="0"),
        sa.Column("avg_proof_time_s", sa.Float, server_default="0.0"),
        sa.Column("uptime_ratio", sa.Float, server_default="1.0"),
        sa.Column("online", sa.Boolean, server_default="1"),
        sa.Column("current_load", sa.Integer, server_default="0"),
        sa.Column("max_concurrent", sa.Integer, server_default="4"),
        sa.Column("last_ping_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("registered_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_prover_capabilities_hotkey", "prover_capabilities", ["hotkey"])
    op.create_index("ix_prover_capabilities_online", "prover_capabilities", ["online"])


def downgrade() -> None:
    op.drop_table("prover_capabilities")
    op.drop_table("proofs")
    op.drop_table("circuit_partitions")
    op.drop_table("proof_jobs")
    op.drop_table("circuits")
    # NOTE: Legacy tables are not re-created on downgrade.
    # If needed, downgrade to revision 0003 and re-apply 0001.
