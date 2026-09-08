"""interference_links: global link blocklist

Revision ID: p48a1b2c3d4e5
Revises: p47a1b2c3d4e5
Create Date: 2026-09-07

干扰链接库：清洗时命中该库链接的商品直接剔除，全平台生效。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p48a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p47a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "interference_links",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("url", sa.String(500), nullable=False),
        sa.Column("remark", sa.String(200), nullable=True),
        sa.Column("created_by", sa.String(50), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_interference_links_url", "interference_links", ["url"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_interference_links_url", table_name="interference_links")
    op.drop_table("interference_links")