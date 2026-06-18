"""user permissions

Revision ID: p28a1b2c3d4e5
Revises: p27a1b2c3d4e5
Create Date: 2026-06-18 00:00:00.000000
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p28a1b2c3d4e5"
down_revision: Union[str, None] = "p27a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("name", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("phone", sa.String(length=50), nullable=True))
    op.add_column("users", sa.Column("email", sa.String(length=100), nullable=True))
    op.add_column("users", sa.Column("is_admin", sa.SmallInteger(), nullable=False, server_default="0"))
    op.add_column("users", sa.Column("permissions", sa.JSON(), nullable=True))
    op.add_column(
        "users",
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
    )
    op.add_column("users", sa.Column("last_login_at", sa.DateTime(), nullable=True))
    op.execute("UPDATE users SET is_admin = 1, name = COALESCE(name, '管理员') WHERE username = 'admin'")


def downgrade() -> None:
    op.drop_column("users", "last_login_at")
    op.drop_column("users", "updated_at")
    op.drop_column("users", "permissions")
    op.drop_column("users", "is_admin")
    op.drop_column("users", "email")
    op.drop_column("users", "phone")
    op.drop_column("users", "name")
