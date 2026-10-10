"""category_extra_fields: make series required for camera

Revision ID: p57a1b2c3d4e5
Revises: p56a1b2c3d4e5
Create Date: 2026-10-10

产品系列（series）在监控摄像头(camera) 设为必填。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p57a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p56a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE category_extra_fields SET required = 1 "
        "WHERE field_key = 'series' AND category_code = 'camera'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE category_extra_fields SET required = 0 "
        "WHERE field_key = 'series' AND category_code = 'camera'"
    )
