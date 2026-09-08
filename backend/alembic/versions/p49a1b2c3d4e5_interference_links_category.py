"""interference_links: optional category scope

Revision ID: p49a1b2c3d4e5
Revises: p48a1b2c3d4e5
Create Date: 2026-09-08

干扰链接库支持可选品类：带品类的链接只在对应品类清洗时生效，category_code 为空表示全平台生效。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p49a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p48a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "interference_links",
        sa.Column("category_code", sa.String(50), nullable=True),
    )
    op.create_index("ix_interference_links_category", "interference_links", ["category_code"])


def downgrade() -> None:
    op.drop_index("ix_interference_links_category", table_name="interference_links")
    op.drop_column("interference_links", "category_code")