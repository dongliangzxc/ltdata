"""match_results: add prev_* snapshot columns for single-row revert

Revision ID: p34a1b2c3d4e5
Revises: p33a1b2c3d4e5
Create Date: 2026-07-12

给 match_results 增加 7 个 prev_* 列，用于人工操作（排除 / 人工确认 / 暂存争议）前的状态快照，
支持单条「撤销」回到上一次操作前的状态。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p34a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p33a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "match_results"

PREV_COLUMNS = [
    sa.Column("prev_match_status", sa.String(length=20), nullable=True),
    sa.Column("prev_model_id", sa.Integer(), nullable=True),
    sa.Column("prev_matched_by", sa.String(length=20), nullable=True),
    sa.Column("prev_match_source", sa.String(length=20), nullable=True),
    sa.Column("prev_dispute_reason", sa.String(length=500), nullable=True),
    sa.Column("prev_review_note", sa.String(length=500), nullable=True),
    sa.Column("prev_reviewed_at", sa.DateTime(), nullable=True),
]


def upgrade() -> None:
    for col in PREV_COLUMNS:
        op.add_column(TABLE_NAME, col)


def downgrade() -> None:
    for col in PREV_COLUMNS:
        op.drop_column(TABLE_NAME, col.name)
