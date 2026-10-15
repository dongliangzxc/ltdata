"""analytics: add published_items lookup indexes

Revision ID: p61a1b2c3d4e5
Revises: p60a1b2c3d4e5
Create Date: 2026-10-15

``published_items`` had no index on ``match_result_id`` or ``clean_job_id``.
Several hot paths therefore degraded to full-table scans on the (multi
million row) analytics table, reading the whole table from disk:

* ``SELECT DISTINCT match_result_id FROM published_items`` — 查询工作台
  「产品系列」筛选 / 导出时每次执行；
* ``SELECT id FROM published_items WHERE clean_job_id = ?`` — 发布/重新发布
  前清理旧数据（``publisher.delete_published_data``）以及工作台按清洗任务过滤。

Adding these indexes lets MySQL serve those lookups (and the DISTINCT loose
index scan) from the index instead of scanning the whole table.
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p61a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p60a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "published_items"
SCHEMA_NAME = "luotu_analytics"

INDEXES = [
    ("ix_published_items_match_result_id", ["match_result_id"]),
    ("ix_published_items_clean_job_id", ["clean_job_id"]),
]


def upgrade() -> None:
    for name, columns in INDEXES:
        op.create_index(
            name,
            TABLE_NAME,
            columns,
            unique=False,
            schema=SCHEMA_NAME,
        )


def downgrade() -> None:
    for name, _columns in INDEXES:
        op.drop_index(name, table_name=TABLE_NAME, schema=SCHEMA_NAME)
