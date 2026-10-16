"""url mappings: widen item_url to TEXT

Revision ID: p63a1b2c3d4e5
Revises: p62a1b2c3d4e5
Create Date: 2026-10-16

抖音商城分享链接（`haohuo.jinritemai.com/...`）带大量埋点/分享参数，长度常超过
``VARCHAR(500)``，导入时触发 ``Data too long for column 'item_url'``。把
``item_url_mappings.item_url`` 放宽为 ``TEXT``。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p63a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p62a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "item_url_mappings"


def upgrade() -> None:
    op.alter_column(
        TABLE_NAME,
        "item_url",
        existing_type=sa.String(500),
        type_=sa.Text(),
        existing_nullable=True,
    )


def downgrade() -> None:
    op.alter_column(
        TABLE_NAME,
        "item_url",
        existing_type=sa.Text(),
        type_=sa.String(500),
        existing_nullable=True,
    )
