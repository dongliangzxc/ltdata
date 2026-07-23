"""upload download jobs

Revision ID: p40a1b2c3d4e5
Revises: p38a1b2c3d4e5, p39a1b2c3d4e5
Create Date: 2026-07-23 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p40a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = ("p38a1b2c3d4e5", "p39a1b2c3d4e5")
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "upload_download_jobs",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("file_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=True),
        sa.Column("progress", sa.SmallInteger(), nullable=True),
        sa.Column("filename", sa.String(length=255), nullable=False),
        sa.Column("download_token", sa.String(length=64), nullable=True),
        sa.Column("error_msg", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["file_id"], ["upload_files.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(op.f("ix_upload_download_jobs_id"), "upload_download_jobs", ["id"], unique=False)
    op.create_index(op.f("ix_upload_download_jobs_file_id"), "upload_download_jobs", ["file_id"], unique=False)
    op.create_index(op.f("ix_upload_download_jobs_download_token"), "upload_download_jobs", ["download_token"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f("ix_upload_download_jobs_download_token"), table_name="upload_download_jobs")
    op.drop_index(op.f("ix_upload_download_jobs_file_id"), table_name="upload_download_jobs")
    op.drop_index(op.f("ix_upload_download_jobs_id"), table_name="upload_download_jobs")
    op.drop_table("upload_download_jobs")
