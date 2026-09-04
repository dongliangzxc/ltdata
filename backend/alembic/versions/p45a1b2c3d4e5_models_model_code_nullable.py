"""models: make model_code nullable

Revision ID: p45a1b2c3d4e5
Revises: p44a1b2c3d4e5
Create Date: 2026-09-04

清洗任务新建型号允许「型号码」留空，留空时存 NULL（不再自动补齐占位码）。
唯一约束 (brand_code, model_code) 保留：MySQL 唯一索引允许多个 NULL，
同品牌可存在多条无型号码型号。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p45a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p44a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("models") as batch_op:
        batch_op.alter_column("model_code", existing_type=sa.String(100), nullable=True)


def downgrade() -> None:
    with op.batch_alter_table("models") as batch_op:
        batch_op.alter_column("model_code", existing_type=sa.String(100), nullable=False)