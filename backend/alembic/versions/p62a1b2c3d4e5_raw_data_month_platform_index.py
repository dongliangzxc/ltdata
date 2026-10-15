"""raw_data: add (month, platform) index for clean monthly pool

Revision ID: p62a1b2c3d4e5
Revises: p61a1b2c3d4e5
Create Date: 2026-10-15

``GET /api/clean/pool/monthly``（待入清洗队列）按 ``raw_data.month`` 与平台聚合
派发明细。原查询需要为每条 ``dispatch_items`` 回表 ``raw_data`` 取 month/platform，
而 ``raw_data`` 含 ``item_name``/``item_url``/``item_image`` 等多个 TEXT 宽字段，
随机回表会放大磁盘读。

新增 ``(month, platform)`` 覆盖索引后，优化器可从该索引取 ``month``/``platform``
（含主键 id）并回连 ``dispatch_items(raw_data_id, category_code, id)``，无需读取
``raw_data`` 的整行，显著降低读盘量。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p62a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p61a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


TABLE_NAME = "raw_data"
INDEX_NAME = "idx_raw_data_month_platform"


def upgrade() -> None:
    op.create_index(INDEX_NAME, TABLE_NAME, ["month", "platform"], unique=False)


def downgrade() -> None:
    op.drop_index(INDEX_NAME, table_name=TABLE_NAME)
