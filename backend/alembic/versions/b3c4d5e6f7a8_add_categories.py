"""add categories table and FK constraints

Revision ID: b3c4d5e6f7a8
Revises: f6a7b8c9d0e1
Create Date: 2026-05-08
"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa

revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, Sequence[str], None] = 'f6a7b8c9d0e1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 0. 清空有 FK 依赖的叶子表（按依赖顺序从叶到根）
    op.execute('DELETE FROM match_result_attrs')   # 依赖 match_results + attr_rules
    op.execute('DELETE FROM match_results')        # 依赖 models（间接）
    op.execute('DELETE FROM historical_mappings')  # 依赖 models
    op.execute('DELETE FROM item_url_mappings')    # 依赖 models
    op.execute('DELETE FROM match_rules')          # 依赖 models
    op.execute('DELETE FROM model_aliases')        # 依赖 models
    op.execute('DELETE FROM model_specs')          # 依赖 models
    op.execute('DELETE FROM models')
    op.execute('DELETE FROM metadata_specs')
    op.execute('DELETE FROM attr_rules')

    # 1. 创建 categories 表
    op.create_table(
        'categories',
        sa.Column('id',         sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('code',       sa.String(50),    nullable=False),
        sa.Column('name',       sa.String(100),   nullable=False),
        sa.Column('created_at', sa.DateTime(),    nullable=False, server_default=sa.text('NOW()')),
        sa.UniqueConstraint('code', name='uq_category_code'),
    )

    # 2. models 表：删除 category_name，新增 category_code FK
    op.drop_column('models', 'category_name')
    op.add_column('models', sa.Column('category_code', sa.String(50), nullable=True))
    op.create_foreign_key(
        'fk_models_category_code', 'models', 'categories',
        ['category_code'], ['code'],
        ondelete='SET NULL',
    )

    # 3. metadata_specs：确保 category_code 可为 NULL（SET NULL FK 需要），加 FK 约束
    op.alter_column('metadata_specs', 'category_code',
                    existing_type=sa.String(100), nullable=True)
    op.create_foreign_key(
        'fk_metadata_category_code', 'metadata_specs', 'categories',
        ['category_code'], ['code'],
        ondelete='SET NULL',
    )

    # 4. attr_rules：加 FK 约束（NULL = 全局，允许 NULL）
    op.create_foreign_key(
        'fk_attr_rules_category_code', 'attr_rules', 'categories',
        ['category_code'], ['code'],
        ondelete='SET NULL',
    )


def downgrade() -> None:
    op.drop_constraint('fk_attr_rules_category_code', 'attr_rules', type_='foreignkey')
    op.drop_constraint('fk_metadata_category_code', 'metadata_specs', type_='foreignkey')
    op.drop_constraint('fk_models_category_code', 'models', type_='foreignkey')
    op.drop_column('models', 'category_code')
    op.add_column('models', sa.Column('category_name', sa.String(200), nullable=True))
    op.drop_table('categories')
