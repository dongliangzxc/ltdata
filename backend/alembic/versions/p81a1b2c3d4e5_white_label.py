"""white-label classification policy and rules

Revision ID: p81a1b2c3d4e5
Revises: p80a1b2c3d4e5
Create Date: 2026-11-26

耳机、无线蓝牙音箱存在大量无品牌/无型号的白牌公模商品。新增品类级白牌
归类策略和关键词规则，把这类商品归到「无品牌 + 类型占位型号」，使其可以
正常发布和统计，同时不进入真实品牌/型号的自动匹配候选。

本迁移同时为 headphone、bt_speaker 初始化占位品牌、占位型号、默认策略
（默认「半自动 suggest」）和常用关键词规则。
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "p81a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p80a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


_GENERIC_BRANDS = (
    ("无品牌", "无品牌"),
    ("其他品牌", "其他品牌"),
)

# category_code -> [(model_code, model_name)]
_PLACEHOLDER_MODELS = {
    "headphone": [
        ("TWS", "真无线"),
        ("INEAR", "入耳式"),
        ("HALF", "半入耳式"),
        ("HEAD", "头戴式"),
        ("NECK", "颈挂式"),
        ("BONE", "骨传导"),
        ("OPEN", "开放式"),
        ("OTHER", "未分类"),
    ],
    "bt_speaker": [
        ("PORT", "便携式"),
        ("DESK", "桌面式"),
        ("OUT", "户外式"),
        ("PARTY", "派对音箱"),
        ("SOUNDBAR", "回音壁"),
        ("OTHER", "未分类"),
    ],
}

# category_code -> [(keyword, model_code, priority)]
_PLACEHOLDER_RULES = {
    "headphone": [
        ("半入耳", "HALF", 10),
        ("骨传导", "BONE", 10),
        ("入耳", "INEAR", 20),
        ("头戴", "HEAD", 20),
        ("耳罩", "HEAD", 20),
        ("颈挂", "NECK", 20),
        ("挂脖", "NECK", 20),
        ("开放", "OPEN", 20),
        ("耳夹", "OPEN", 20),
        ("真无线", "TWS", 30),
    ],
    "bt_speaker": [
        ("回音壁", "SOUNDBAR", 10),
        ("条形", "SOUNDBAR", 20),
        ("派对", "PARTY", 10),
        ("便携", "PORT", 20),
        ("户外", "OUT", 30),
        ("桌面", "DESK", 20),
        ("电脑音响", "DESK", 20),
    ],
}


def _first_id(conn, sql: str, params: dict):
    row = conn.execute(sa.text(sql), params).first()
    return row[0] if row else None


def _ensure_brand(conn, brand_code: str, brand_name: str) -> None:
    exists = _first_id(
        conn,
        "SELECT id FROM brands WHERE brand_code = :code LIMIT 1",
        {"code": brand_code},
    )
    if exists:
        return
    conn.execute(
        sa.text(
            "INSERT INTO brands "
            "(brand_code, brand_name, original_brand_name, status, created_at, updated_at) "
            "VALUES (:code, :name, :name, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {"code": brand_code, "name": brand_name},
    )


def _ensure_model(conn, brand_code: str, category_code: str, model_code: str, model_name: str):
    exists = _first_id(
        conn,
        "SELECT id FROM models WHERE brand_code = :brand AND category_code = :category "
        "AND model_code = :model AND COALESCE(series, '') = '' LIMIT 1",
        {"brand": brand_code, "category": category_code, "model": model_code},
    )
    if exists:
        return exists
    result = conn.execute(
        sa.text(
            "INSERT INTO models "
            "(brand_code, model_code, category_code, brand_name, model_name, status, created_at, updated_at) "
            "VALUES (:brand, :model, :category, :brand_name, :model_name, 'active', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "brand": brand_code,
            "model": model_code,
            "category": category_code,
            "brand_name": brand_code,
            "model_name": model_name,
        },
    )
    return result.lastrowid


def _category_exists(conn, category_code: str) -> bool:
    return _first_id(
        conn,
        "SELECT id FROM categories WHERE code = :code LIMIT 1",
        {"code": category_code},
    ) is not None


def upgrade() -> None:
    op.create_table(
        "white_label_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(50), nullable=False, comment="品类码"),
        sa.Column("enabled", sa.SmallInteger(), nullable=False, server_default="0", comment="是否启用自动归类"),
        sa.Column("mode", sa.String(20), nullable=False, server_default="off", comment="off/suggest/auto"),
        sa.Column("brand_code", sa.String(100), nullable=False, server_default="无品牌", comment="占位品牌"),
        sa.Column("unmatched_model_id", sa.Integer(), nullable=True, comment="未命中关键词时的兜底占位型号"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["category_code"], ["categories.code"],
            name="fk_white_label_policies_category", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["unmatched_model_id"], ["models.id"],
            name="fk_white_label_policies_unmatched_model", ondelete="SET NULL",
        ),
        sa.UniqueConstraint("category_code", name="uq_white_label_policy_category"),
    )

    op.create_table(
        "white_label_rules",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("category_code", sa.String(50), nullable=False, comment="品类码"),
        sa.Column("keyword", sa.String(200), nullable=False, comment="标题关键词"),
        sa.Column("match_type", sa.String(20), nullable=False, server_default="contains", comment="contains/exact"),
        sa.Column("model_id", sa.Integer(), nullable=False, comment="命中的占位型号（类型）"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="100", comment="越小越先执行"),
        sa.Column("is_active", sa.SmallInteger(), nullable=False, server_default="1", comment="是否启用"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(
            ["category_code"], ["categories.code"],
            name="fk_white_label_rules_category", ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["model_id"], ["models.id"],
            name="fk_white_label_rules_model", ondelete="CASCADE",
        ),
        sa.UniqueConstraint("category_code", "keyword", "model_id", name="uq_white_label_rule"),
        sa.CheckConstraint("match_type IN ('contains', 'exact')", name="ck_white_label_rule_type"),
    )
    op.create_index(
        "idx_white_label_rule_category", "white_label_rules",
        ["category_code", "is_active", "priority"],
    )

    conn = op.get_bind()
    for brand_code, brand_name in _GENERIC_BRANDS:
        _ensure_brand(conn, brand_code, brand_name)

    for category_code, models in _PLACEHOLDER_MODELS.items():
        if not _category_exists(conn, category_code):
            continue
        model_ids = {}
        for model_code, model_name in models:
            model_ids[model_code] = _ensure_model(
                conn, "无品牌", category_code, model_code, model_name,
            )

        policy_id = _first_id(
            conn,
            "SELECT id FROM white_label_policies WHERE category_code = :category LIMIT 1",
            {"category": category_code},
        )
        if policy_id is None:
            conn.execute(
                sa.text(
                    "INSERT INTO white_label_policies "
                    "(category_code, enabled, mode, brand_code, unmatched_model_id, created_at, updated_at) "
                    "VALUES (:category, 1, 'suggest', '无品牌', :unmatched, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {"category": category_code, "unmatched": model_ids.get("OTHER")},
            )

        for keyword, model_code, priority in _PLACEHOLDER_RULES.get(category_code, []):
            model_id = model_ids.get(model_code)
            if not model_id:
                continue
            rule_id = _first_id(
                conn,
                "SELECT id FROM white_label_rules WHERE category_code = :category "
                "AND keyword = :keyword AND model_id = :model LIMIT 1",
                {"category": category_code, "keyword": keyword, "model": model_id},
            )
            if rule_id is not None:
                continue
            conn.execute(
                sa.text(
                    "INSERT INTO white_label_rules "
                    "(category_code, keyword, match_type, model_id, priority, is_active, created_at, updated_at) "
                    "VALUES (:category, :keyword, 'contains', :model, :priority, 1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
                ),
                {
                    "category": category_code,
                    "keyword": keyword,
                    "model": model_id,
                    "priority": priority,
                },
            )


def downgrade() -> None:
    op.drop_index("idx_white_label_rule_category", table_name="white_label_rules")
    op.drop_table("white_label_rules")
    op.drop_table("white_label_policies")
