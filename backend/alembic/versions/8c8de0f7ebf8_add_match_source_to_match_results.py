"""add match_source to match_results

Revision ID: 8c8de0f7ebf8
Revises: 
Create Date: 2026-04-29 14:49:58.140117

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '8c8de0f7ebf8'
down_revision: Union[str, Sequence[str], None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        'match_results',
        sa.Column('match_source', sa.String(20), nullable=True,
                  comment='s1/s2/s3/s4=自动匹配步骤 manual=人工')
    )


def downgrade() -> None:
    op.drop_column('match_results', 'match_source')
