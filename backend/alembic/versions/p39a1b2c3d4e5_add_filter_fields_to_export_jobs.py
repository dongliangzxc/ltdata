"""add filter fields to export jobs

Revision ID: p39a1b2c3d4e5
Revises: p37a1b2c3d4e5
Create Date: 2026-07-19
"""
from alembic import op
import sqlalchemy as sa


revision = "p39a1b2c3d4e5"
down_revision = "p37a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("export_jobs", sa.Column("months", sa.JSON(), nullable=True))
    op.add_column("export_jobs", sa.Column("category_code", sa.String(length=100), nullable=True))
    op.add_column("export_jobs", sa.Column("platforms", sa.JSON(), nullable=True))
    op.alter_column("export_jobs", "clean_job_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    op.alter_column("export_jobs", "clean_job_id", existing_type=sa.Integer(), nullable=False)
    op.drop_column("export_jobs", "platforms")
    op.drop_column("export_jobs", "category_code")
    op.drop_column("export_jobs", "months")
