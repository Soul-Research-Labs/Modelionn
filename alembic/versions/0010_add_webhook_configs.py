"""add webhook_configs table

Revision ID: 0010
Revises: 0009
Create Date: 2026-06-15

Re-adds webhook_configs table for user-managed webhook endpoints.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "0010"
down_revision = "0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "webhook_configs",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("hotkey", sa.String(128), nullable=False, index=True),
        sa.Column("url", sa.String(2048), nullable=False),
        sa.Column("label", sa.String(128), server_default=""),
        sa.Column("events", sa.Text, nullable=False, server_default="*"),
        sa.Column("secret", sa.String(64), nullable=False),
        sa.Column("active", sa.Boolean, nullable=False, server_default=sa.text("1")),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_triggered_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_webhook_hotkey_active", "webhook_configs", ["hotkey", "active"])


def downgrade() -> None:
    op.drop_table("webhook_configs")
