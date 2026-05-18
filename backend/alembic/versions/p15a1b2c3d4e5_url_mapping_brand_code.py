"""item_url_mappings 加 brand_code 列，支持品牌已知但型号未知的 URL 条目

Revision ID: p15a1b2c3d4e5
Revises: p14a1b2c3d4e5
Create Date: 2026-05-18
"""
import sqlalchemy as sa
from alembic import op

revision = 'p15a1b2c3d4e5'
down_revision = 'p14a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column(
        'item_url_mappings',
        sa.Column('brand_code', sa.String(100), nullable=True),
    )
    # 回填：有 model_id 的条目从 models 表取 brand_code
    op.execute("""
        UPDATE item_url_mappings ium
        JOIN models m ON ium.model_id = m.id
        SET ium.brand_code = m.brand_code
        WHERE ium.brand_code IS NULL AND ium.model_id IS NOT NULL
    """)


def downgrade():
    op.drop_column('item_url_mappings', 'brand_code')
