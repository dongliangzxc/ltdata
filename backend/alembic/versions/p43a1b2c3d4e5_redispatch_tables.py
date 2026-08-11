"""batch redispatch job tables

Revision ID: p43a1b2c3d4e5
Revises: p42a1b2c3d4e5
Create Date: 2026-08-11 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p43a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p42a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dispatch_redispatch_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("category_code", sa.String(length=50), nullable=False),
        sa.Column("skip_contained", sa.SmallInteger(), nullable=False, server_default=sa.text("0")),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("total_batches", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("done_batches", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("success_batches", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("failed_batches", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("skipped_batches", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_dispatch_redispatch_jobs_id"), "dispatch_redispatch_jobs", ["id"], unique=False)
    op.create_index(op.f("ix_dispatch_redispatch_jobs_category_code"), "dispatch_redispatch_jobs", ["category_code"], unique=False)

    op.create_table(
        "dispatch_redispatch_job_items",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("batch_id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default=sa.text("'pending'")),
        sa.Column("new_batch_id", sa.Integer(), nullable=True),
        sa.Column("dispatched_rows", sa.Integer(), nullable=True),
        sa.Column("unmatched_rows", sa.Integer(), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["job_id"], ["dispatch_redispatch_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_id", "batch_id", name="uq_redispatch_job_batch"),
    )
    op.create_index(op.f("ix_dispatch_redispatch_job_items_id"), "dispatch_redispatch_job_items", ["id"], unique=False)
    op.create_index(op.f("ix_dispatch_redispatch_job_items_job_id"), "dispatch_redispatch_job_items", ["job_id"], unique=False)
    op.create_index(op.f("ix_dispatch_redispatch_job_items_batch_id"), "dispatch_redispatch_job_items", ["batch_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_dispatch_redispatch_job_items_batch_id"), table_name="dispatch_redispatch_job_items")
    op.drop_index(op.f("ix_dispatch_redispatch_job_items_job_id"), table_name="dispatch_redispatch_job_items")
    op.drop_index(op.f("ix_dispatch_redispatch_job_items_id"), table_name="dispatch_redispatch_job_items")
    op.drop_table("dispatch_redispatch_job_items")

    op.drop_index(op.f("ix_dispatch_redispatch_jobs_category_code"), table_name="dispatch_redispatch_jobs")
    op.drop_index(op.f("ix_dispatch_redispatch_jobs_id"), table_name="dispatch_redispatch_jobs")
    op.drop_table("dispatch_redispatch_jobs")
