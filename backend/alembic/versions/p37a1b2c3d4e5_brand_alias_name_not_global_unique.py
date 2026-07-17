"""brand_aliases: allow duplicate alias text across brands

Revision ID: p37a1b2c3d4e5
Revises: p36a1b2c3d4e5
Create Date: 2026-07-16

品牌别名只归属于当前品牌，不再要求 alias_name 在全表唯一。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p37a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p36a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("brand_aliases") as batch_op:
        batch_op.drop_constraint("alias_name", type_="unique")


def downgrade() -> None:
    with op.batch_alter_table("brand_aliases") as batch_op:
        batch_op.create_unique_constraint("alias_name", ["alias_name"])
