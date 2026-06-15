"""category task snapshots

Revision ID: p26a1b2c3d4e5
Revises: p25a1b2c3d4e5
Create Date: 2026-06-14 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p26a1b2c3d4e5"
down_revision: Union[str, None] = "p25a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("clean_jobs", sa.Column("task_name", sa.String(length=200), nullable=True))
    op.add_column("clean_jobs", sa.Column("category_code", sa.String(length=50), nullable=True))
    op.add_column("clean_jobs", sa.Column("platform", sa.String(length=50), nullable=True))
    op.add_column("clean_jobs", sa.Column("source_scope", sa.JSON(), nullable=True))
    op.create_index(op.f("ix_clean_jobs_category_code"), "clean_jobs", ["category_code"], unique=False)
    op.create_index(op.f("ix_clean_jobs_platform"), "clean_jobs", ["platform"], unique=False)

    op.create_table(
        "clean_job_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("clean_job_id", sa.Integer(), nullable=False),
        sa.Column("raw_data_id", sa.Integer(), nullable=False),
        sa.Column("category_code", sa.String(length=50), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=True),
        sa.Column("dispatch_batch_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["clean_job_id"], ["clean_jobs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["raw_data_id"], ["raw_data.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("raw_data_id", "category_code", name="uq_clean_job_item_raw_category"),
    )
    op.create_index(op.f("ix_clean_job_items_id"), "clean_job_items", ["id"], unique=False)
    op.create_index("idx_clean_job_items_job", "clean_job_items", ["clean_job_id"], unique=False)
    op.create_index(
        "idx_clean_job_items_category_platform",
        "clean_job_items",
        ["category_code", "platform"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_clean_job_items_category_platform", table_name="clean_job_items")
    op.drop_index("idx_clean_job_items_job", table_name="clean_job_items")
    op.drop_index(op.f("ix_clean_job_items_id"), table_name="clean_job_items")
    op.drop_table("clean_job_items")

    op.drop_index(op.f("ix_clean_jobs_platform"), table_name="clean_jobs")
    op.drop_index(op.f("ix_clean_jobs_category_code"), table_name="clean_jobs")
    op.drop_column("clean_jobs", "source_scope")
    op.drop_column("clean_jobs", "platform")
    op.drop_column("clean_jobs", "category_code")
    op.drop_column("clean_jobs", "task_name")
