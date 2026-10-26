"""translation cache for overseas product names

Revision ID: p70a1b2c3d4e5
Revises: p69a1b2c3d4e5
Create Date: 2026-10-23
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p70a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p69a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "translation_cache" not in inspector.get_table_names():
        op.create_table(
            "translation_cache",
            sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
            sa.Column("source_hash", sa.String(length=64), nullable=False),
            sa.Column("source_text", sa.Text(), nullable=True),
            sa.Column("source_lang", sa.String(length=16), nullable=False, server_default="auto"),
            sa.Column("target_lang", sa.String(length=16), nullable=False, server_default="zh-CN"),
            sa.Column("provider", sa.String(length=32), nullable=False),
            sa.Column("translated_text", sa.Text(), nullable=False),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("source_hash", "target_lang", "provider", name="uq_translation_cache"),
        )
        op.create_index("idx_translation_cache_hash", "translation_cache", ["source_hash"], unique=False)


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    if "translation_cache" in inspector.get_table_names():
        op.drop_table("translation_cache")
