"""match_results: add adjusted price

Revision ID: p38a1b2c3d4e5
Revises: p37a1b2c3d4e5
Create Date: 2026-07-17

单条匹配结果支持人工调整现价格，保留原始 raw_data.price 不被覆盖。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p38a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p37a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("match_results") as batch_op:
        batch_op.add_column(sa.Column("adjusted_price", sa.Numeric(10, 2), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("match_results") as batch_op:
        batch_op.drop_column("adjusted_price")
