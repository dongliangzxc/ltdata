"""P4: add match_result_candidates table

Revision ID: p4c3d4e5f6a7
Revises: b2c3d4e5f6a1
Create Date: 2026-05-09
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = 'p4c3d4e5f6a7'
down_revision: Union[str, Sequence[str], None] = 'b2c3d4e5f6a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'match_result_candidates',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('match_result_id', sa.Integer, sa.ForeignKey('match_results.id'), nullable=False),
        sa.Column('model_id', sa.Integer, nullable=False),
        sa.Column('match_source', sa.String(20), nullable=True),
        sa.Column('score', sa.Integer, nullable=False),
        sa.Column('rank', sa.Integer, nullable=False),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
    )
    op.create_index('idx_mrc_match_result_id', 'match_result_candidates', ['match_result_id'])


def downgrade() -> None:
    op.drop_index('idx_mrc_match_result_id', table_name='match_result_candidates')
    op.drop_table('match_result_candidates')
