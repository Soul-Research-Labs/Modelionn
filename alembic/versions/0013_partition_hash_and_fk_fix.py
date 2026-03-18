"""add commitment_hash to partitions and fix soft-delete FK

Revision ID: 0013_partition_hash_and_fk_fix
Revises: 0012_add_composite_indexes
Create Date: 2026-03-19 10:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0013_partition_hash_and_fk_fix'
down_revision: Union[str, None] = '0012_add_composite_indexes'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add commitment_hash column to circuit_partitions for fragment validation
    op.add_column(
        'circuit_partitions',
        sa.Column('commitment_hash', sa.String(64), nullable=True),
    )

    # Change proof_jobs.circuit_id FK from CASCADE to RESTRICT
    # so soft-deleted circuits don't accidentally hard-delete jobs
    op.drop_constraint(
        'fk_proof_jobs_circuit_id_circuits',
        'proof_jobs',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_proof_jobs_circuit_id_circuits',
        'proof_jobs',
        'circuits',
        ['circuit_id'],
        ['id'],
        ondelete='RESTRICT',
    )


def downgrade() -> None:
    op.drop_constraint(
        'fk_proof_jobs_circuit_id_circuits',
        'proof_jobs',
        type_='foreignkey',
    )
    op.create_foreign_key(
        'fk_proof_jobs_circuit_id_circuits',
        'proof_jobs',
        'circuits',
        ['circuit_id'],
        ['id'],
        ondelete='CASCADE',
    )

    op.drop_column('circuit_partitions', 'commitment_hash')
