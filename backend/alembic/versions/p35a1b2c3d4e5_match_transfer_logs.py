"""match_transfer_logs: 新增单条转移审计日志表

Revision ID: p35a1b2c3d4e5
Revises: p34a1b2c3d4e5
Create Date: 2026-07-12

「任务复核工作台单条转移」功能的审计表，记录每次把 match_result 从一个 clean_job
硬迁到另一个 clean_job 的历史（不可撤销）。字段与 backend/app/models/schemas.py
的 MatchTransferLog ORM 对齐；同步 sql/migrations/20260712_add_match_transfer_logs.sql。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p35a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p34a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "match_transfer_logs",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("match_result_id", sa.BigInteger(), nullable=False),
        sa.Column("raw_data_id", sa.BigInteger(), nullable=False),
        sa.Column("from_clean_job_id", sa.Integer(), nullable=False),
        sa.Column("to_clean_job_id", sa.Integer(), nullable=False),
        sa.Column("operator", sa.String(length=100), nullable=True),
        sa.Column(
            "transferred_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        mysql_engine="InnoDB",
        mysql_charset="utf8mb4",
    )
    op.create_index("idx_mtl_from_job", "match_transfer_logs", ["from_clean_job_id"])
    op.create_index("idx_mtl_to_job", "match_transfer_logs", ["to_clean_job_id"])
    op.create_index("idx_mtl_match_result", "match_transfer_logs", ["match_result_id"])


def downgrade() -> None:
    op.drop_index("idx_mtl_match_result", table_name="match_transfer_logs")
    op.drop_index("idx_mtl_to_job", table_name="match_transfer_logs")
    op.drop_index("idx_mtl_from_job", table_name="match_transfer_logs")
    op.drop_table("match_transfer_logs")
