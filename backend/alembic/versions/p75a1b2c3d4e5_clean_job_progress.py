"""clean jobs: progress / stage / error

Revision ID: p75a1b2c3d4e5
Revises: p74a1b2c3d4e5
Create Date: 2026-11-13

清洗任务改为后台异步执行后，前端需要轮询进度：
- progress: 0-100 百分比
- progress_stage: 当前阶段（清洗中/匹配中/失败等）
- error_msg: 后台失败原因
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p75a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p74a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "clean_jobs",
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("clean_jobs", sa.Column("progress_stage", sa.String(30), nullable=True))
    op.add_column("clean_jobs", sa.Column("error_msg", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("clean_jobs", "error_msg")
    op.drop_column("clean_jobs", "progress_stage")
    op.drop_column("clean_jobs", "progress")
