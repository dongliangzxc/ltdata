"""interference_links: category required (strict per-category)

Revision ID: p50a1b2c3d4e5
Revises: p49a1b2c3d4e5
Create Date: 2026-09-08

干扰链接必须绑定品类：清洗时只应用当前品类的链接，不再存在“全平台”链接。
（生产当前无历史 NULL 数据，可直接收紧为 NOT NULL。）
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "p50a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p49a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.alter_column(
        "interference_links",
        "category_code",
        existing_type=sa.String(50),
        nullable=False,
    )


def downgrade() -> None:
    op.alter_column(
        "interference_links",
        "category_code",
        existing_type=sa.String(50),
        nullable=True,
    )