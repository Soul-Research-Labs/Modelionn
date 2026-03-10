"""add performance indexes

Revision ID: 0002_add_indexes
Revises: 0001_initial_schema
Create Date: 2026-03-09
"""

from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index("ix_artifact_task", "artifacts", ["task"])
    op.create_index("ix_artifact_framework", "artifacts", ["framework"])
    op.create_index("ix_artifact_created_at", "artifacts", ["created_at"])
    op.create_index("ix_artifact_downloads", "artifacts", ["downloads"])


def downgrade() -> None:
    op.drop_index("ix_artifact_downloads", table_name="artifacts")
    op.drop_index("ix_artifact_created_at", table_name="artifacts")
    op.drop_index("ix_artifact_framework", table_name="artifacts")
    op.drop_index("ix_artifact_task", table_name="artifacts")
