"""initial schema

Revision ID: 0001
Revises: 
Create Date: 2026-03-09

All tables from registry/models/database.py.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Organizations ────────────────────────────────────────
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("slug", sa.String(128), nullable=False, unique=True),
        sa.Column("settings_json", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_organizations_slug", "organizations", ["slug"])

    # ── Users ────────────────────────────────────────────────
    op.create_table(
        "users",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("hotkey", sa.String(128), nullable=False, unique=True),
        sa.Column("display_name", sa.String(128), server_default=""),
        sa.Column("email", sa.String(256), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_users_hotkey", "users", ["hotkey"])

    # ── Memberships ──────────────────────────────────────────
    op.create_table(
        "memberships",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer, nullable=False),
        sa.Column("org_id", sa.Integer, nullable=False),
        sa.Column("role", sa.String(16), nullable=False, server_default="viewer"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_memberships_user_id", "memberships", ["user_id"])
    op.create_index("ix_memberships_org_id", "memberships", ["org_id"])
    op.create_index("ix_membership_user_org", "memberships", ["user_id", "org_id"], unique=True)

    # ── Audit Logs ───────────────────────────────────────────
    op.create_table(
        "audit_logs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Integer, nullable=True),
        sa.Column("actor_hotkey", sa.String(128), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("resource_type", sa.String(64), nullable=False),
        sa.Column("resource_id", sa.String(256), nullable=False),
        sa.Column("old_value", sa.Text, nullable=True),
        sa.Column("new_value", sa.Text, nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_audit_logs_org_id", "audit_logs", ["org_id"])
    op.create_index("ix_audit_logs_actor_hotkey", "audit_logs", ["actor_hotkey"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])
    op.create_index("ix_audit_org_created", "audit_logs", ["org_id", "created_at"])
    op.create_index("ix_audit_resource", "audit_logs", ["resource_type", "resource_id"])

    # ── Artifacts ────────────────────────────────────────────
    op.create_table(
        "artifacts",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Integer, nullable=True),
        sa.Column("artifact_type", sa.String(32), nullable=False),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("version", sa.String(64), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("ipfs_cid", sa.String(128), nullable=False, unique=True),
        sa.Column("sha256_hash", sa.String(64), nullable=False),
        sa.Column("size_bytes", sa.Integer, server_default="0"),
        sa.Column("publisher_hotkey", sa.String(128), nullable=False),
        sa.Column("tags_csv", sa.Text, server_default=""),
        sa.Column("downloads", sa.Integer, server_default="0"),
        # Model-specific
        sa.Column("architecture", sa.String(128), nullable=True),
        sa.Column("framework", sa.String(32), nullable=True),
        sa.Column("task", sa.String(64), nullable=True),
        sa.Column("license", sa.String(32), nullable=True),
        sa.Column("config_json", sa.Text, nullable=True),
        # Dataset-specific
        sa.Column("format", sa.String(64), nullable=True),
        sa.Column("num_samples", sa.Integer, nullable=True),
        # Benchmark-specific
        sa.Column("metrics_schema_json", sa.Text, nullable=True),
        # Subnet module-specific
        sa.Column("subnet_type", sa.String(32), nullable=True),
        sa.Column("compatible_netuid", sa.Integer, nullable=True),
        # Reproducibility
        sa.Column("reproducibility_json", sa.Text, nullable=True),
        # Fingerprint + embeddings
        sa.Column("fingerprint", sa.String(64), nullable=True),
        sa.Column("embedding_json", sa.Text, nullable=True),
        sa.Column("quality_score", sa.Float, nullable=True),
        # Timestamps
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_artifacts_org_id", "artifacts", ["org_id"])
    op.create_index("ix_artifacts_artifact_type", "artifacts", ["artifact_type"])
    op.create_index("ix_artifacts_publisher_hotkey", "artifacts", ["publisher_hotkey"])
    op.create_index("ix_artifacts_fingerprint", "artifacts", ["fingerprint"])
    op.create_index("ix_name_version", "artifacts", ["name", "version"], unique=True)

    # ── Artifact Tags ────────────────────────────────────────
    op.create_table(
        "artifact_tags",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(256), nullable=False),
        sa.Column("tag", sa.String(64), nullable=False),
        sa.Column("artifact_id", sa.Integer, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_artifact_tags_artifact_id", "artifact_tags", ["artifact_id"])
    op.create_index("ix_tag_name_tag", "artifact_tags", ["name", "tag"], unique=True)

    # ── Publisher Reputation ─────────────────────────────────
    op.create_table(
        "publisher_reputation",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("hotkey", sa.String(128), nullable=False, unique=True),
        sa.Column("artifact_count", sa.Integer, server_default="0"),
        sa.Column("avg_benchmark_score", sa.Float, server_default="0.0"),
        sa.Column("reproducibility_rate", sa.Float, server_default="0.0"),
        sa.Column("stake", sa.Float, server_default="0.0"),
        sa.Column("reputation_score", sa.Float, server_default="0.0"),
        sa.Column("total_downloads", sa.Integer, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_publisher_reputation_hotkey", "publisher_reputation", ["hotkey"])

    # ── Model Cards ──────────────────────────────────────────
    op.create_table(
        "model_cards",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("artifact_id", sa.Integer, nullable=False, unique=True),
        sa.Column("content_md", sa.Text, server_default=""),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_model_cards_artifact_id", "model_cards", ["artifact_id"])

    # ── API Keys ─────────────────────────────────────────────
    op.create_table(
        "api_keys",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("key_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("hotkey", sa.String(128), nullable=False),
        sa.Column("label", sa.String(128), server_default=""),
        sa.Column("requests_today", sa.Integer, server_default="0"),
        sa.Column("daily_limit", sa.Integer, server_default="1000"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_api_keys_key_hash", "api_keys", ["key_hash"])
    op.create_index("ix_api_keys_hotkey", "api_keys", ["hotkey"])

    # ── Benchmark Scores ─────────────────────────────────────
    op.create_table(
        "benchmark_scores",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("artifact_id", sa.Integer, nullable=False),
        sa.Column("benchmark_name", sa.String(256), nullable=False),
        sa.Column("metric_name", sa.String(128), nullable=False),
        sa.Column("value", sa.Float, nullable=False),
        sa.Column("evaluator_hotkey", sa.String(128), nullable=True),
        sa.Column("evaluated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_benchmark_scores_artifact_id", "benchmark_scores", ["artifact_id"])

    # ── Bounties ─────────────────────────────────────────────
    op.create_table(
        "bounties",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("target_artifact_name", sa.String(256), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("description", sa.Text, server_default=""),
        sa.Column("severity_min", sa.String(16), nullable=False, server_default="low"),
        sa.Column("reward_tao", sa.Float, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="open"),
        sa.Column("publisher_hotkey", sa.String(128), nullable=False),
        sa.Column("claimed_by", sa.String(128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_bounties_target_artifact_name", "bounties", ["target_artifact_name"])
    op.create_index("ix_bounties_status", "bounties", ["status"])
    op.create_index("ix_bounties_publisher_hotkey", "bounties", ["publisher_hotkey"])

    # ── Vulnerability Reports ────────────────────────────────
    op.create_table(
        "vulnerability_reports",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("bounty_id", sa.Integer, nullable=True),
        sa.Column("reporter_hotkey", sa.String(128), nullable=False),
        sa.Column("target_artifact_name", sa.String(256), nullable=False),
        sa.Column("severity", sa.String(16), nullable=False),
        sa.Column("title", sa.String(256), nullable=False),
        sa.Column("writeup_md", sa.Text, server_default=""),
        sa.Column("exploit_artifact_name", sa.String(256), nullable=True),
        sa.Column("exploit_artifact_version", sa.String(64), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="embargoed"),
        sa.Column("embargo_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("disclosed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vulnerability_reports_bounty_id", "vulnerability_reports", ["bounty_id"])
    op.create_index("ix_vulnerability_reports_reporter_hotkey", "vulnerability_reports", ["reporter_hotkey"])
    op.create_index("ix_vulnerability_reports_target_artifact_name", "vulnerability_reports", ["target_artifact_name"])

    # ── Commit Reveals ───────────────────────────────────────
    op.create_table(
        "commit_reveals",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("artifact_name", sa.String(256), nullable=False),
        sa.Column("commit_hash", sa.String(64), nullable=False),
        sa.Column("nonce_hash", sa.String(64), nullable=True),
        sa.Column("committer_hotkey", sa.String(128), nullable=False),
        sa.Column("committed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("revealed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("reveal_status", sa.String(32), nullable=False, server_default="pending"),
    )
    op.create_index("ix_commit_reveals_artifact_name", "commit_reveals", ["artifact_name"])
    op.create_index("ix_commit_reveals_commit_hash", "commit_reveals", ["commit_hash"])
    op.create_index("ix_commit_reveals_committer_hotkey", "commit_reveals", ["committer_hotkey"])

    # ── Eval Jobs ────────────────────────────────────────────
    op.create_table(
        "eval_jobs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.String(64), nullable=False, unique=True),
        sa.Column("artifact_id", sa.Integer, nullable=False),
        sa.Column("artifact_name", sa.String(256), nullable=False),
        sa.Column("artifact_version", sa.String(64), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        sa.Column("submitter_hotkey", sa.String(128), nullable=False),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("result_json", sa.Text, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_eval_jobs_task_id", "eval_jobs", ["task_id"])
    op.create_index("ix_eval_jobs_artifact_id", "eval_jobs", ["artifact_id"])
    op.create_index("ix_eval_jobs_status", "eval_jobs", ["status"])
    op.create_index("ix_eval_jobs_submitter_hotkey", "eval_jobs", ["submitter_hotkey"])

    # ── Validator States ─────────────────────────────────────
    op.create_table(
        "validator_states",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("hotkey", sa.String(128), nullable=False, unique=True),
        sa.Column("total_validations", sa.Integer, server_default="0"),
        sa.Column("agreements", sa.Integer, server_default="0"),
        sa.Column("divergences", sa.Integer, server_default="0"),
        sa.Column("reliability_score", sa.Float, server_default="1.0"),
        sa.Column("slashed", sa.Boolean, server_default="0"),
        sa.Column("slash_count", sa.Integer, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_validator_states_hotkey", "validator_states", ["hotkey"])

    # ── Webhook Configs ──────────────────────────────────────
    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Integer, nullable=False),
        sa.Column("url", sa.String(1024), nullable=False),
        sa.Column("secret", sa.String(256), nullable=False),
        sa.Column("events_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_webhook_configs_org_id", "webhook_configs", ["org_id"])

    # ── Notification Configs ─────────────────────────────────
    op.create_table(
        "notification_configs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("org_id", sa.Integer, nullable=False),
        sa.Column("channel_type", sa.String(32), nullable=False),
        sa.Column("webhook_url", sa.String(1024), nullable=False),
        sa.Column("events_json", sa.Text, nullable=False, server_default="[]"),
        sa.Column("active", sa.Boolean, server_default="1"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_notification_configs_org_id", "notification_configs", ["org_id"])


def downgrade() -> None:
    op.drop_table("notification_configs")
    op.drop_table("webhook_configs")
    op.drop_table("validator_states")
    op.drop_table("eval_jobs")
    op.drop_table("commit_reveals")
    op.drop_table("vulnerability_reports")
    op.drop_table("bounties")
    op.drop_table("benchmark_scores")
    op.drop_table("api_keys")
    op.drop_table("model_cards")
    op.drop_table("publisher_reputation")
    op.drop_table("artifact_tags")
    op.drop_table("artifacts")
    op.drop_table("audit_logs")
    op.drop_table("memberships")
    op.drop_table("users")
    op.drop_table("organizations")
