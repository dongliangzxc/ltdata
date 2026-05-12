"""P10: add module column to column_templates

Revision ID: p10a1b2c3d4e5
Revises: p9a1b2c3d4e5
Create Date: 2026-05-12
"""
from alembic import op
import sqlalchemy as sa

revision = 'p10a1b2c3d4e5'
down_revision = 'p9a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Add module column with default 'sales'
    op.add_column(
        'column_templates',
        sa.Column('module', sa.String(20), nullable=False, server_default='sales'),
    )
    # Drop old unique constraint on (name)
    op.drop_index('uq_template_name', table_name='column_templates')
    # Create new unique constraint on (module, name)
    op.create_index(
        'uq_module_template_name',
        'column_templates',
        ['module', 'name'],
        unique=True,
    )
    # Set built-in templates (京东月报, 天猫/淘宝月报) to module='sales'
    op.execute(
        "UPDATE column_templates SET module = 'sales' WHERE is_builtin = 1"
    )


def downgrade() -> None:
    op.drop_index('uq_module_template_name', table_name='column_templates')
    op.drop_column('column_templates', 'module')
    op.create_index('uq_template_name', 'column_templates', ['name'], unique=True)
