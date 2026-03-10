"""add FK constraints, webhook deliveries table, and new indexes

Revision ID: 0003
Revises: 0002_add_indexes
Create Date: 2026-03-09

Adds:
- Foreign key constraints on memberships, artifact_tags, model_cards,
  benchmark_scores, eval_jobs
- webhook_deliveries table (for delivery tracking / DLQ)
- Indexes on quality_score, expires_at, reputation_score
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0003"
down_revision = "0002_add_indexes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── Foreign key constraints ──────────────────────────────
    with op.batch_alter_table("memberships") as batch_op:
        batch_op.create_foreign_key(
            "fk_memberships_user_id", "users", ["user_id"], ["id"], ondelete="CASCADE"
        )
        batch_op.create_foreign_key(
            "fk_memberships_org_id", "organizations", ["org_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("artifact_tags") as batch_op:
        batch_op.create_foreign_key(
            "fk_artifact_tags_artifact_id", "artifacts", ["artifact_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("model_cards") as batch_op:
        batch_op.create_foreign_key(
            "fk_model_cards_artifact_id", "artifacts", ["artifact_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("benchmark_scores") as batch_op:
        batch_op.create_foreign_key(
            "fk_benchmark_scores_artifact_id", "artifacts", ["artifact_id"], ["id"], ondelete="CASCADE"
        )

    with op.batch_alter_table("eval_jobs") as batch_op:
        batch_op.create_foreign_key(
            "fk_eval_jobs_artifact_id", "artifacts", ["artifact_id"], ["id"], ondelete="CASCADE"
        )

    # ── New indexes ──────────────────────────────────────────
    op.create_index("ix_artifact_quality_score", "artifacts", ["quality_score"])
    op.create_index("ix_bounties_expires_at", "bounties", ["expires_at"])
    op.create_index("ix_publisher_reputation_score", "publisher_reputation", ["reputation_score"])
    op.create_index("ix_bs_artifact_benchmark", "benchmark_scores", ["artifact_id", "benchmark_name", "metric_name"])

    # ── Webhook deliveries table ─────────────────────────────
    op.create_table(
        "webhook_deliveries",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column(
            "webhook_id",
            sa.Integer,
            sa.ForeignKey("webhook_configs.id"),
            nullable=False,
            index=True,
        ),
        sa.Column("event", sa.String(64), nullable=False),
        sa.Column("payload_json", sa.Text, nullable=False),
        sa.Column("status", sa.String(16), nullable=False, server_default="pending"),
        sa.Column("attempts", sa.Integer, server_default="0"),
        sa.Column("http_status", sa.Integer, nullable=True),
        sa.Column("error", sa.Text, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
        ),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_deliveries_status", "webhook_deliveries", ["status"])


def downgrade() -> None:
    op.drop_table("webhook_deliveries")

    op.drop_index("ix_bs_artifact_benchmark", table_name="benchmark_scores")
    op.drop_index("ix_publisher_reputation_score", table_name="publisher_reputation")
    op.drop_index("ix_bounties_expires_at", table_name="bounties")
    op.drop_index("ix_artifact_quality_score", table_name="artifacts")

    with op.batch_alter_table("eval_jobs") as batch_op:
        batch_op.drop_constraint("fk_eval_jobs_artifact_id", type_="foreignkey")

    with op.batch_alter_table("benchmark_scores") as batch_op:
        batch_op.drop_constraint("fk_benchmark_scores_artifact_id", type_="foreignkey")

    with op.batch_alter_table("model_cards") as batch_op:
        batch_op.drop_constraint("fk_model_cards_artifact_id", type_="foreignkey")

    with op.batch_alter_table("artifact_tags") as batch_op:
        batch_op.drop_constraint("fk_artifact_tags_artifact_id", type_="foreignkey")

    with op.batch_alter_table("memberships") as batch_op:
        batch_op.drop_constraint("fk_memberships_org_id", type_="foreignkey")
        batch_op.drop_constraint("fk_memberships_user_id", type_="foreignkey")
