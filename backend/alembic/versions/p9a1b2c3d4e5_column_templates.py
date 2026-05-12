"""P9 — column templates for flexible upload mapping

Revision ID: p9a1b2c3d4e5
Revises: p8a1b2c3d4e5
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa
import json

revision = 'p9a1b2c3d4e5'
down_revision = 'p8a1b2c3d4e5'
branch_labels = None
depends_on = None


_JD_MAPPING = {
    "平台": "platform", "月": "month",
    "Lv0类目名称(逐月固定)": "category_lv0",
    "Lv1类目名称(逐月固定)": "category_lv1",
    "Lv2类目名称(逐月固定)": "category_lv2",
    "宝贝ID": "item_id", "宝贝名称": "item_name",
    "宝贝图片": "item_image", "宝贝链接": "item_url",
    "参考价格": "ref_price", "宝贝品牌(bid)": "brand_raw",
    "宝贝店铺名称": "shop_name", "销量": "sales_qty",
    "销售额": "sales_amount", "价格": "price",
    "品牌": "brand_std", "机型": "model_std",
}

_TM_MAPPING = {
    "平台": "platform", "月": "month",
    "Lv1类目名称(逐月固定)": "category_lv1",
    "Lv2类目名称(逐月固定)": "category_lv2",
    "Lv3类目名称(逐月固定)": "category_lv3",
    "Lv4类目名称(逐月固定)": "category_lv4",
    "Lv5类目名称(逐月固定)": "category_lv5",
    "宝贝ID": "item_id", "宝贝名称": "item_name",
    "宝贝图片": "item_image", "宝贝链接": "item_url",
    "参考价格": "ref_price", "宝贝品牌": "brand_raw",
    "宝贝店铺名称": "shop_name", "销量": "sales_qty",
    "销售额": "sales_amount", "价格": "price",
    "品牌": "brand_std", "机型": "model_std",
}


def _fingerprint(mapping: dict) -> str:
    import hashlib
    cols = sorted(mapping.keys())
    return hashlib.md5(",".join(cols).encode()).hexdigest()


def upgrade():
    op.create_table(
        'column_templates',
        sa.Column('id', sa.Integer, primary_key=True, autoincrement=True),
        sa.Column('name', sa.String(100), nullable=False),
        sa.Column('platform', sa.String(50), nullable=True),
        sa.Column('col_fingerprint', sa.String(32), nullable=True),
        sa.Column('mapping', sa.JSON, nullable=False),
        sa.Column('ignore_columns', sa.JSON, nullable=True),
        sa.Column('is_builtin', sa.SmallInteger, nullable=False, server_default='0'),
        sa.Column('created_at', sa.DateTime, server_default=sa.func.now()),
        sa.Column('updated_at', sa.DateTime, server_default=sa.func.now(),
                  onupdate=sa.func.now()),
    )
    op.add_column('upload_files',
        sa.Column('template_id', sa.Integer, nullable=True,
                  comment='本次上传使用的列模板 ID'))

    # Insert two built-in templates
    bind = op.get_bind()
    for row in [
        {"name": "京东月报", "platform": "jd",
         "fp": _fingerprint(_JD_MAPPING),
         "mapping": json.dumps(_JD_MAPPING, ensure_ascii=False),
         "ignore": json.dumps([])},
        {"name": "天猫/淘宝月报", "platform": "tmall",
         "fp": _fingerprint(_TM_MAPPING),
         "mapping": json.dumps(_TM_MAPPING, ensure_ascii=False),
         "ignore": json.dumps([])},
    ]:
        bind.execute(
            sa.text(
                "INSERT INTO column_templates (name, platform, col_fingerprint, mapping, ignore_columns, is_builtin) "
                "VALUES (:name, :platform, :fp, :mapping, :ignore, 1)"
            ),
            row
        )


def downgrade():
    op.drop_column('upload_files', 'template_id')
    op.drop_table('column_templates')
