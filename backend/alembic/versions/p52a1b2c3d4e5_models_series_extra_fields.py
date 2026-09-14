"""models: add series column + category_extra_fields config

Revision ID: p52a1b2c3d4e5
Revises: p51a1b2c3d4e5
Create Date: 2026-09-14

产品属性管理支持按品类配置额外字段（不同品类新增不同字段）。
当前规则：智能平板(tablet)、学习平板(edu_tablet) 需要额外维护「产品系列」series 字段。
新增 category_extra_fields 配置表 + models.series 列，便于后续按品类继续扩展其他字段。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p52a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p51a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_EXTRA_FIELDS = [
    ("tablet",    "series", "产品系列"),
    ("edu_tablet", "series", "产品系列"),
]


def upgrade() -> None:
    op.add_column(
        "models",
        sa.Column("series", sa.String(200), nullable=True, comment="产品系列（品类扩展字段）"),
    )

    op.create_table(
        "category_extra_fields",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(50), nullable=False, comment="品类码"),
        sa.Column("field_key", sa.String(100), nullable=False, comment="字段键，对应 models 列（如 series）"),
        sa.Column("field_label", sa.String(200), nullable=False, comment="字段展示名（如 产品系列）"),
        sa.Column("field_type", sa.String(50), nullable=False, server_default="text", comment="字段类型（text/select 等）"),
        sa.Column("required", sa.Integer(), nullable=False, server_default="0", comment="是否必填 0/1"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值，越小越靠前"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("category_code", "field_key", name="uq_category_extra_field"),
    )
    op.create_index("ix_category_extra_fields_category", "category_extra_fields", ["category_code"])

    for category_code, field_key, field_label in _EXTRA_FIELDS:
        op.execute(
            f"INSERT IGNORE INTO category_extra_fields (category_code, field_key, field_label, field_type, required, sort_order) "
            f"VALUES ('{category_code}', '{field_key}', '{field_label}', 'text', 0, 1)"
        )


def downgrade() -> None:
    op.drop_index("ix_category_extra_fields_category", table_name="category_extra_fields")
    op.drop_table("category_extra_fields")
    op.drop_column("models", "series")