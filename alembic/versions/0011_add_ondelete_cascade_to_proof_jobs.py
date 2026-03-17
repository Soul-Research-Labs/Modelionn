"""add ondelete cascade to proof jobs

Revision ID: 0011_add_ondelete_cascade
Revises: 0010_add_webhook_configs
Create Date: 2026-03-17 12:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '0011_add_ondelete_cascade'
down_revision: Union[str, None] = '0010_add_webhook_configs'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Drop existing foreign key and recreate it with ON DELETE CASCADE
    with op.batch_alter_table('proof_jobs') as batch_op:
        batch_op.drop_constraint('fk_proof_jobs_circuit_id_circuits', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_proof_jobs_circuit_id_circuits',
            'circuits',
            ['circuit_id'],
            ['id'],
            ondelete='CASCADE'
        )

def downgrade() -> None:
    with op.batch_alter_table('proof_jobs') as batch_op:
        batch_op.drop_constraint('fk_proof_jobs_circuit_id_circuits', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_proof_jobs_circuit_id_circuits',
            'circuits',
            ['circuit_id'],
            ['id']
        )
