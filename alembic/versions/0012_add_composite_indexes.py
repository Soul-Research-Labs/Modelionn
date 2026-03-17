"""add composite indexes for query performance

Revision ID: 0012_add_composite_indexes
Revises: 0011_add_ondelete_cascade
Create Date: 2026-03-18 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = '0012_add_composite_indexes'
down_revision: Union[str, None] = '0011_add_ondelete_cascade'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # proof_jobs(status, started_at) — cleanup_stale_jobs queries both
    op.create_index(
        'ix_proof_jobs_status_started_at',
        'proof_jobs',
        ['status', 'started_at'],
    )

    # proof_jobs(result_proof_id) — list_proofs JOIN on this column
    op.create_index(
        'ix_proof_jobs_result_proof_id',
        'proof_jobs',
        ['result_proof_id'],
    )

    # prover_capabilities(online, last_ping_at) — health-check eviction query
    op.create_index(
        'ix_prover_capabilities_online_last_ping',
        'prover_capabilities',
        ['online', 'last_ping_at'],
    )

    # circuits(publisher_hotkey, deleted_at) — rate-limit + soft-delete filter
    op.create_index(
        'ix_circuits_publisher_deleted',
        'circuits',
        ['publisher_hotkey', 'deleted_at'],
    )

    # circuit_partitions(job_id, status) — partition reassignment queries
    op.create_index(
        'ix_circuit_partitions_job_status',
        'circuit_partitions',
        ['job_id', 'status'],
    )

    # circuits(circuit_type, deleted_at) — filtered listing by type
    op.create_index(
        'ix_circuits_type_deleted',
        'circuits',
        ['circuit_type', 'deleted_at'],
    )


def downgrade() -> None:
    op.drop_index('ix_circuits_type_deleted', table_name='circuits')
    op.drop_index('ix_circuit_partitions_job_status', table_name='circuit_partitions')
    op.drop_index('ix_circuits_publisher_deleted', table_name='circuits')
    op.drop_index('ix_prover_capabilities_online_last_ping', table_name='prover_capabilities')
    op.drop_index('ix_proof_jobs_result_proof_id', table_name='proof_jobs')
    op.drop_index('ix_proof_jobs_status_started_at', table_name='proof_jobs')
