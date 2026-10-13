"""Add the composite lookup index used by upload deduplication.

The initial SQL schema has a unique key on this tuple, but older databases
created through an earlier migration path may not.  This non-unique index is
safe in either case and keeps the 5,000-key deduplication queries from
scanning the complete raw_data table.
"""
from typing import Sequence, Union

from alembic import op
from sqlalchemy import inspect


revision: str = "p60a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p59a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

INDEX_NAME = "idx_raw_dedup_lookup"


def upgrade() -> None:
    bind = op.get_bind()
    inspector = inspect(bind)
    existing = inspector.get_indexes("raw_data")
    unique = inspector.get_unique_constraints("raw_data")
    dedup_columns = ("item_id", "month", "platform")
    has_equivalent = any(
        tuple(item.get("column_names") or ()) == dedup_columns
        for item in [*existing, *unique]
    )
    # The initial SQL schema already has a unique key with these columns.  A
    # second index would only make every bulk insert more expensive.
    if not has_equivalent:
        op.create_index(INDEX_NAME, "raw_data", ["item_id", "month", "platform"])


def downgrade() -> None:
    bind = op.get_bind()
    existing = {item["name"] for item in inspect(bind).get_indexes("raw_data")}
    if INDEX_NAME in existing:
        op.drop_index(INDEX_NAME, table_name="raw_data")
