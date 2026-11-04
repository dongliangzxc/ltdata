"""category custom fields + match result extra values

Revision ID: p72a1b2c3d4e5
Revises: p71a1b2c3d4e5
Create Date: 2026-11-03

品类清洗扩展字段：支持按品类配置条目级自定义列（如智能投影的「智能」），
字段配置存 category_custom_fields，人工值存 match_result_extra_values。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p72a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p71a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "category_custom_fields",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(50), nullable=False, comment="品类码"),
        sa.Column("field_key", sa.String(100), nullable=False, comment="字段键（英文）"),
        sa.Column("field_label", sa.String(200), nullable=False, comment="字段展示名"),
        sa.Column("field_type", sa.String(20), nullable=False, server_default="enum", comment="enum/text/bool/number"),
        sa.Column("options", sa.Text(), nullable=True, comment="枚举可选值，逗号分隔"),
        sa.Column("default_value", sa.String(200), nullable=True, comment="默认值"),
        sa.Column("auto_keywords", sa.Text(), nullable=True, comment="自动判定关键词"),
        sa.Column("auto_value", sa.String(200), nullable=True, comment="命中关键词后的取值"),
        sa.Column("required", sa.Integer(), nullable=False, server_default="0", comment="是否必填"),
        sa.Column("export", sa.Integer(), nullable=False, server_default="1", comment="是否参与导出"),
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0", comment="排序值"),
        sa.Column("is_active", sa.Integer(), nullable=False, server_default="1", comment="是否启用"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.UniqueConstraint("category_code", "field_key", name="uq_category_custom_field"),
    )
    op.create_index("ix_category_custom_fields_category", "category_custom_fields", ["category_code"])

    op.create_table(
        "match_result_extra_values",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("match_result_id", sa.Integer(), nullable=False, comment="匹配结果 ID"),
        sa.Column("field_key", sa.String(100), nullable=False, comment="字段键"),
        sa.Column("field_value", sa.String(200), nullable=True, comment="字段值"),
        sa.Column("source", sa.String(20), nullable=False, server_default="manual", comment="manual/auto"),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["match_result_id"], ["match_results.id"],
            name="fk_match_result_extra_values_match_result",
            ondelete="CASCADE",
        ),
        sa.UniqueConstraint("match_result_id", "field_key", name="uq_match_result_extra_field"),
    )
    op.create_index("ix_match_result_extra_values_match_result_id", "match_result_extra_values", ["match_result_id"])
    op.create_index("idx_mrextra_field_value", "match_result_extra_values", ["field_key", "field_value"])


def downgrade() -> None:
    op.drop_index("idx_mrextra_field_value", table_name="match_result_extra_values")
    op.drop_index("ix_match_result_extra_values_match_result_id", table_name="match_result_extra_values")
    op.drop_table("match_result_extra_values")
    op.drop_index("ix_category_custom_fields_category", table_name="category_custom_fields")
    op.drop_table("category_custom_fields")
