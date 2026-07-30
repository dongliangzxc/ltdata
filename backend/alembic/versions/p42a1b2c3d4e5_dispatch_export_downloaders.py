"""add dispatch export downloader list

Revision ID: p42a1b2c3d4e5
Revises: p41a1b2c3d4e5
Create Date: 2026-07-30 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p42a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p41a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workbench_export_jobs", sa.Column("downloaders", sa.JSON(), nullable=True))
    op.add_column("workbench_export_jobs", sa.Column("last_download_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("workbench_export_jobs", "last_download_at")
    op.drop_column("workbench_export_jobs", "downloaders")
