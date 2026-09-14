"""category_extra_fields: make series required for tablet/edu_tablet

Revision ID: p53a1b2c3d4e5
Revises: p52a1b2c3d4e5
Create Date: 2026-09-14

产品系列（series）在智能平板(tablet)、学习平板(edu_tablet) 设为必填。
"""
from typing import Sequence, Union

from alembic import op


revision: str = "p53a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p52a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        "UPDATE category_extra_fields SET required = 1 "
        "WHERE field_key = 'series' AND category_code IN ('tablet', 'edu_tablet')"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE category_extra_fields SET required = 0 "
        "WHERE field_key = 'series' AND category_code IN ('tablet', 'edu_tablet')"
    )