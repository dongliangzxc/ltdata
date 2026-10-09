"""category_extra_fields: enable 产品系列 for camera / vrar

Revision ID: p56a1b2c3d4e5
Revises: p55a1b2c3d4e5
Create Date: 2026-10-09

监控摄像头(camera)、XR和智能眼镜(vrar) 需要按「品牌 + 产品系列 + 型号」处理，
与智能平板/学习平板一致。为这两个品类启用产品系列扩展字段（非必填）。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p56a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p55a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_CATEGORY_CODES = ("camera", "vrar")


def upgrade() -> None:
    for category_code in _CATEGORY_CODES:
        op.execute(
            "INSERT IGNORE INTO category_extra_fields "
            "(category_code, field_key, field_label, field_type, required, sort_order) "
            f"VALUES ('{category_code}', 'series', '产品系列', 'text', 0, 1)"
        )


def downgrade() -> None:
    codes = ",".join(f"'{code}'" for code in _CATEGORY_CODES)
    op.execute(
        f"DELETE FROM category_extra_fields WHERE field_key = 'series' AND category_code IN ({codes})"
    )
