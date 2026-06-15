"""clean page performance indexes

Revision ID: p27a1b2c3d4e5
Revises: p26a1b2c3d4e5
Create Date: 2026-06-15 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p27a1b2c3d4e5"
down_revision: Union[str, None] = "p26a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "idx_match_results_job_status",
        "match_results",
        ["clean_job_id", "match_status"],
        unique=False,
    )
    op.create_index(
        "idx_dispatch_items_raw_category_id",
        "dispatch_items",
        ["raw_data_id", "category_code", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_dispatch_items_raw_category_id", table_name="dispatch_items")
    op.drop_index("idx_match_results_job_status", table_name="match_results")
