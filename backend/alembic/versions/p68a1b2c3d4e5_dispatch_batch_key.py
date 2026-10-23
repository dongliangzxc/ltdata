"""dispatch_batches: add batch_key for batch-wide dispatch

Revision ID: p68a1b2c3d4e5
Revises: p67a1b2c3d4e5
Create Date: 2026-10-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p68a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p67a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("dispatch_batches")}
    if "batch_key" not in columns:
        op.add_column("dispatch_batches", sa.Column("batch_key", sa.String(length=64), nullable=True, comment="上传批次标识；为空表示单文件分发"))
    indexes = {index["name"] for index in inspector.get_indexes("dispatch_batches")}
    if "ix_dispatch_batches_batch_key" not in indexes:
        op.create_index("ix_dispatch_batches_batch_key", "dispatch_batches", ["batch_key"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("dispatch_batches")}
    if "ix_dispatch_batches_batch_key" in indexes:
        op.drop_index("ix_dispatch_batches_batch_key", table_name="dispatch_batches")
    columns = {column["name"] for column in inspector.get_columns("dispatch_batches")}
    if "batch_key" in columns:
        op.drop_column("dispatch_batches", "batch_key")
