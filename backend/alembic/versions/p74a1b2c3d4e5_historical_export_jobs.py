"""historical export jobs

Revision ID: p74a1b2c3d4e5
Revises: p73a1b2c3d4e5
Create Date: 2026-11-05

历史库导出改为后台任务：大批次（百万行级）在线程内分页写入 Excel，
前端轮询进度，避免同步导出超过行数上限或请求超时。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p74a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p73a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "historical_export_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("import_batch", sa.String(200), nullable=True),
        sa.Column("category_codes", sa.JSON(), nullable=True),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("filename", sa.String(500), nullable=True),
        sa.Column("file_token", sa.String(64), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "idx_hist_export_jobs_token",
        "historical_export_jobs",
        ["file_token"],
    )


def downgrade() -> None:
    op.drop_index("idx_hist_export_jobs_token", table_name="historical_export_jobs")
    op.drop_table("historical_export_jobs")
