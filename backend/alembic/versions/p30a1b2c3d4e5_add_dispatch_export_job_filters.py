"""add dispatch export job filters

Revision ID: p30a1b2c3d4e5
Revises: p29a1b2c3d4e5
Create Date: 2026-07-06 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "p30a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p29a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workbench_export_jobs", sa.Column("category_code", sa.String(length=50), nullable=True))
    op.add_column("workbench_export_jobs", sa.Column("platform", sa.String(length=50), nullable=True))
    op.add_column("workbench_export_jobs", sa.Column("month", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("workbench_export_jobs", "month")
    op.drop_column("workbench_export_jobs", "platform")
    op.drop_column("workbench_export_jobs", "category_code")
