"""raw_data: add filename source category fields

Revision ID: p69a1b2c3d4e5
Revises: p68a1b2c3d4e5
Create Date: 2026-10-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p69a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p68a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    columns = {column["name"] for column in inspector.get_columns("raw_data")}
    if "source_category_code" not in columns:
        op.add_column("raw_data", sa.Column("source_category_code", sa.String(length=50), nullable=True, comment="文件名识别出的品类码"))
        op.create_index("ix_raw_data_source_category_code", "raw_data", ["source_category_code"], unique=False)
    if "source_category_name" not in columns:
        op.add_column("raw_data", sa.Column("source_category_name", sa.String(length=200), nullable=True, comment="文件名识别出的品类名称"))


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    indexes = {index["name"] for index in inspector.get_indexes("raw_data")}
    if "ix_raw_data_source_category_code" in indexes:
        op.drop_index("ix_raw_data_source_category_code", table_name="raw_data")
    columns = {column["name"] for column in inspector.get_columns("raw_data")}
    if "source_category_name" in columns:
        op.drop_column("raw_data", "source_category_name")
    if "source_category_code" in columns:
        op.drop_column("raw_data", "source_category_code")
