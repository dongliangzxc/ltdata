"""analytics: add published_items model/month index

Revision ID: p33a1b2c3d4e5
Revises: p32a1b2c3d4e5
Create Date: 2026-07-10

Add a composite index used by price audit history lookups.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p33a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p32a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEX_NAME = "ix_published_items_model_code_month"
TABLE_NAME = "published_items"
SCHEMA_NAME = "luotu_analytics"


def upgrade() -> None:
    op.create_index(
        INDEX_NAME,
        TABLE_NAME,
        ["model_code", "month"],
        unique=False,
        schema=SCHEMA_NAME,
    )


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME, schema=SCHEMA_NAME)
