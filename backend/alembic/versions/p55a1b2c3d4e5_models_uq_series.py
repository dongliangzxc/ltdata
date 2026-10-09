"""models: unique key includes series via functional index

Revision ID: p55a1b2c3d4e5
Revises: p54a1b2c3d4e5
Create Date: 2026-10-09

智能平板/学习平板的业务唯一键为「品牌 + 产品系列 + 型号码(存储)」，
因此 models 唯一索引从 (brand_code, model_code, category_code) 调整为
(brand_code, category_code, COALESCE(series,''), model_code)。

用 COALESCE(series,'') 做函数索引，使 series 为 NULL 的非系列品类
等价于原 (brand_code, category_code, model_code) 唯一性，行为不变、无需改数据。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p55a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p54a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("ALTER TABLE models DROP INDEX uq_model")
    op.execute(
        "CREATE UNIQUE INDEX uq_model ON models "
        "(brand_code, category_code, (COALESCE(series,'')), model_code)"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE models DROP INDEX uq_model")
    op.execute(
        "CREATE UNIQUE INDEX uq_model ON models "
        "(brand_code, model_code, category_code)"
    )
