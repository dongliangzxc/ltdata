"""upload_files: add batch_key for grouped upload history

Revision ID: p67a1b2c3d4e5
Revises: p66a1b2c3d4e5
Create Date: 2026-10-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p67a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p66a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("upload_files")}
    if "batch_key" not in columns:
        op.add_column(
            "upload_files",
            sa.Column("batch_key", sa.String(length=64), nullable=True, comment="一次批量确认入库的批次标识"),
        )
    indexes = {index["name"] for index in inspector.get_indexes("upload_files")}
    if "ix_upload_files_batch_key" not in indexes:
        op.create_index("ix_upload_files_batch_key", "upload_files", ["batch_key"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("upload_files")}
    if "ix_upload_files_batch_key" in indexes:
        op.drop_index("ix_upload_files_batch_key", table_name="upload_files")
    columns = {column["name"] for column in inspector.get_columns("upload_files")}
    if "batch_key" in columns:
        op.drop_column("upload_files", "batch_key")
