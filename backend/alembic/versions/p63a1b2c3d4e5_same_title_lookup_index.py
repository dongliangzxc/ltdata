"""raw_data: persist normalized title keys for same-title review lookups.

The same-title endpoints used to load every MatchResult in a clean job and
call ``title_key`` in Python.  Persisting the exact application normalization
key allows the database to narrow the join before loading the three result
objects.  Existing rows are backfilled in small batches so the migration does
not build a several-hundred-thousand-row Python list.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

from app.utils.text_utils import title_key


revision: str = "p63a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p62a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "raw_data",
        sa.Column(
            "item_name_norm",
            sa.String(length=1000),
            nullable=True,
            comment="title_key(item_name) for same-title lookup",
        ),
    )
    # The prefix keeps the utf8mb4 index below InnoDB's key-size limit.  The
    # equality predicate still compares the complete VARCHAR value after the
    # index narrows candidates.
    op.create_index(
        "idx_raw_data_item_name_norm",
        "raw_data",
        ["item_name_norm", "id"],
        unique=False,
        mysql_length={"item_name_norm": 255},
    )
    op.create_index(
        "idx_match_results_job_raw",
        "match_results",
        ["clean_job_id", "raw_data_id"],
        unique=False,
    )

    bind = op.get_bind()
    update = sa.text(
        "UPDATE raw_data SET item_name_norm = :item_name_norm "
        "WHERE id = :id"
    )
    last_id = 0
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT id, item_name FROM raw_data "
                "WHERE id > :last_id ORDER BY id LIMIT 1000"
            ),
            {"last_id": last_id},
        ).mappings().all()
        if not rows:
            break
        values = [
            {
                "id": row["id"],
                "item_name_norm": title_key(row["item_name"]) or None,
            }
            for row in rows
        ]
        bind.execute(update, values)
        last_id = rows[-1]["id"]


def downgrade() -> None:
    op.drop_index("idx_match_results_job_raw", table_name="match_results")
    op.drop_index("idx_raw_data_item_name_norm", table_name="raw_data")
    op.drop_column("raw_data", "item_name_norm")
