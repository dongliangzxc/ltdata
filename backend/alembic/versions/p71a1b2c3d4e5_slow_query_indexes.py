"""add indexes for slow dispatch/raw-data/match queries

Revision ID: p71a1b2c3d4e5
Revises: p70a1b2c3d4e5
Create Date: 2026-10-30

第一批慢查询索引：
- dispatch_items(batch_id, category_code, raw_data_id)：分发批次列表 EXISTS 与
  分发结果导出按批次+品类取明细。
- match_results(match_status, id)：匹配结果全局汇总按状态过滤。
- cleaned_data(clean_job_id, raw_data_id)：匹配结果汇总/导出按任务+原始行 join。
- raw_data(brand_std)：原始数据筛选项 DISTINCT brand_std。

MySQL DDL 非事务，迁移按索引是否存在做幂等处理，失败后可重复执行。
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "p71a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p70a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


INDEXES = [
    ("dispatch_items", "idx_dispatch_batch_category_raw", ["batch_id", "category_code", "raw_data_id"]),
    ("match_results", "idx_match_status_id", ["match_status", "id"]),
    ("cleaned_data", "idx_cleaned_job_raw", ["clean_job_id", "raw_data_id"]),
    ("raw_data", "idx_raw_brand_std", ["brand_std"]),
]


def _index_names(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, index_name, columns in INDEXES:
        if index_name in _index_names(inspector, table):
            continue
        column_sql = ", ".join(f"`{column}`" for column in columns)
        op.execute(
            f"ALTER TABLE `{table}` ADD INDEX `{index_name}` ({column_sql}) "
            ", ALGORITHM=INPLACE, LOCK=NONE"
        )
        inspector = sa.inspect(bind)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    for table, index_name, _columns in reversed(INDEXES):
        if index_name not in _index_names(inspector, table):
            continue
        op.execute(f"ALTER TABLE `{table}` DROP INDEX `{index_name}`")
        inspector = sa.inspect(bind)
