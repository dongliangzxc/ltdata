"""add dispatch export job params

Revision ID: p31a1b2c3d4e5
Revises: p30a1b2c3d4e5
Create Date: 2026-07-07 00:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "p31a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p30a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("workbench_export_jobs", sa.Column("params", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("workbench_export_jobs", "params")
