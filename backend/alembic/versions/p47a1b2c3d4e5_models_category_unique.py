"""models unique key includes category_code

Revision ID: p47a1b2c3d4e5
Revises: p46a1b2c3d4e5
Create Date: 2026-09-07

同一「品牌码 + 型号码」允许出现在多个品类下（如创维/100DSV5 既属于电视也属于会议电视），
每个品类作为独立型号记录存在。唯一约束由 (brand_code, model_code) 放宽为
(brand_code, model_code, category_code)。
"""
from typing import Sequence, Union

from alembic import op

revision: str = "p47a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p46a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index("uq_model", table_name="models")
    op.create_index(
        "uq_model",
        "models",
        ["brand_code", "model_code", "category_code"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_model", table_name="models")
    op.create_index(
        "uq_model",
        "models",
        ["brand_code", "model_code"],
        unique=True,
    )