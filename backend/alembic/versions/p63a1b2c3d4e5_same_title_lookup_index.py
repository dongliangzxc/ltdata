"""raw_data: persist normalized title keys for same-title review lookups.

The same-title endpoints used to load every MatchResult in a clean job and
call ``title_key`` in Python.  Persisting the exact application normalization
key allows the database to narrow the join before loading the three result
objects.  Existing rows that participate in a match are backfilled in small
batches so the migration does not scan unrelated historical uploads or build
a several-hundred-thousand-row Python list.
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
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # MySQL DDL is non-transactional.  If a deployment is interrupted while
    # the backfill is running, the column/indexes may already exist while
    # alembic_version is still p62.  Make the migration safe to resume.
    raw_columns = {column["name"] for column in inspector.get_columns("raw_data")}
    if "item_name_norm" not in raw_columns:
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
    raw_indexes = {index["name"] for index in inspector.get_indexes("raw_data")}
    if "idx_raw_data_item_name_norm" not in raw_indexes:
        op.create_index(
            "idx_raw_data_item_name_norm",
            "raw_data",
            ["item_name_norm", "id"],
            unique=False,
            mysql_length={"item_name_norm": 255},
        )
    match_indexes = {index["name"] for index in inspector.get_indexes("match_results")}
    if "idx_match_results_job_raw" not in match_indexes:
        op.create_index(
            "idx_match_results_job_raw",
            "match_results",
            ["clean_job_id", "raw_data_id"],
            unique=False,
        )

    # Only raw rows that already participate in a match can be reached by the
    # same-title review endpoint.  Backfilling the entire raw_data table made
    # a deploy scan millions of historical upload rows that are irrelevant to
    # the feature; the DISTINCT join keeps this one-time migration bounded by
    # the much smaller match_results set.
    update = sa.text(
        "UPDATE raw_data SET item_name_norm = :item_name_norm "
        "WHERE id = :id AND item_name_norm IS NULL"
    )
    last_id = 0
    while True:
        rows = bind.execute(
            sa.text(
                "SELECT rd.id, rd.item_name "
                "FROM raw_data rd "
                "JOIN (SELECT DISTINCT raw_data_id FROM match_results "
                "      WHERE raw_data_id IS NOT NULL) mr "
                "  ON mr.raw_data_id = rd.id "
                "WHERE rd.id > :last_id AND rd.item_name_norm IS NULL "
                "ORDER BY rd.id LIMIT 1000"
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
