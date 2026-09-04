"""historical_mappings: add model_type

Revision ID: p44a1b2c3d4e5
Revises: p43a1b2c3d4e5
Create Date: 2026-09-04

历史库导入支持独立的「机型/系列」字段存储（如 Excel 中的 机型、系列/机型、产品系列 列），
与「型号」字段分开保存。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p44a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p43a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("historical_mappings") as batch_op:
        batch_op.add_column(sa.Column("model_type", sa.String(200), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("historical_mappings") as batch_op:
        batch_op.drop_column("model_type")