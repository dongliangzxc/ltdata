"""users: add category permissions

Revision ID: p39a1b2c3d4e5
Revises: p38a1b2c3d4e5
Create Date: 2026-07-30
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p39a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p38a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.add_column(sa.Column("category_permissions", sa.JSON(), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("users") as batch_op:
        batch_op.drop_column("category_permissions")
