"""clean_jobs: add updated_at (最近处理时间)

Revision ID: p54a1b2c3d4e5
Revises: p53a1b2c3d4e5
Create Date: 2026-09-22

清洗任务增加 updated_at 字段，用于按最近处理时间排序。
历史数据回填为 created_at。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p54a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p53a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clean_jobs", sa.Column("updated_at", sa.DateTime, nullable=True))
    op.execute("UPDATE clean_jobs SET updated_at = created_at WHERE updated_at IS NULL")
    op.alter_column("clean_jobs", "updated_at", type_=sa.DateTime(), nullable=False)


def downgrade() -> None:
    op.drop_column("clean_jobs", "updated_at")