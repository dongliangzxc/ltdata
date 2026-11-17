"""Persistent serial cleaning queue with independently stored progress.

Revision ID: p76a1b2c3d4e5
Revises: p75a1b2c3d4e5
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.mysql import DATETIME

revision = "p76a1b2c3d4e5"
down_revision = "p75a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "clean_task_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("clean_job_id", sa.Integer(), sa.ForeignKey("clean_jobs.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("state", sa.String(20), nullable=False),
        sa.Column("stage", sa.String(30), nullable=False),
        sa.Column("processed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("worker_token", sa.String(36)),
        sa.Column("queued_at", sa.DateTime().with_variant(DATETIME(fsp=6), "mysql"), nullable=False),
        sa.Column("started_at", sa.DateTime()),
        sa.Column("finished_at", sa.DateTime()),
    )
    op.create_index("idx_clean_runs_queue", "clean_task_runs", ["state", "queued_at", "id"])


def downgrade():
    op.drop_table("clean_task_runs")
