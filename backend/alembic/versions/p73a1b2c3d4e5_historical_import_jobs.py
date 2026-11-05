"""historical import jobs

Revision ID: p73a1b2c3d4e5
Revises: p72a1b2c3d4e5
Create Date: 2026-11-04

历史库大文件导入改为后台任务：解析/写入过程持久化进度，前端轮询，
避免单个 HTTP 请求因上传或处理时间过长被网关/浏览器中断。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p73a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p72a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "historical_import_jobs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("progress", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("stage", sa.String(30), nullable=False, server_default="pending"),
        sa.Column("stage_label", sa.String(100), nullable=False, server_default="等待处理"),
        sa.Column("import_batch", sa.String(200), nullable=True),
        sa.Column("filename", sa.String(500), nullable=True),
        sa.Column("total_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("processed_files", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_rows", sa.Integer(), nullable=True),
        sa.Column("processed_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("success_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_rows", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("files_data", sa.JSON(), nullable=True),
        sa.Column("result_data", sa.JSON(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
    )
    op.create_index("idx_hist_import_jobs_status", "historical_import_jobs", ["status", "created_at"])


def downgrade() -> None:
    op.drop_index("idx_hist_import_jobs_status", table_name="historical_import_jobs")
    op.drop_table("historical_import_jobs")
