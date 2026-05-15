"""P11: fast file deletion — raw_data batch delete + dispatch FK SET NULL

Revision ID: p11a1b2c3d4e5
Revises: 6ec3f5339928
Create Date: 2026-05-15
"""
from alembic import op
import sqlalchemy as sa

revision = 'p11a1b2c3d4e5'
down_revision = '6ec3f5339928'
branch_labels = None
depends_on = None


def upgrade() -> None:
    # dispatch_items: raw_data_id NOT NULL + CASCADE → NULL + SET NULL
    with op.batch_alter_table('dispatch_items', recreate='always') as batch_op:
        batch_op.alter_column(
            'raw_data_id',
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.drop_constraint('fk_di_raw', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_di_raw',
            'raw_data',
            ['raw_data_id'], ['id'],
            ondelete='SET NULL',
        )

    # dispatch_batches: file_id NOT NULL + RESTRICT → NULL + SET NULL
    with op.batch_alter_table('dispatch_batches', recreate='always') as batch_op:
        batch_op.alter_column(
            'file_id',
            existing_type=sa.Integer(),
            nullable=True,
        )
        batch_op.drop_constraint('fk_db_file', type_='foreignkey')
        batch_op.create_foreign_key(
            'fk_db_file',
            'upload_files',
            ['file_id'], ['id'],
            ondelete='SET NULL',
        )


def downgrade() -> None:
    with op.batch_alter_table('dispatch_batches', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_db_file', type_='foreignkey')
        batch_op.alter_column(
            'file_id',
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            'fk_db_file',
            'upload_files',
            ['file_id'], ['id'],
        )

    with op.batch_alter_table('dispatch_items', recreate='always') as batch_op:
        batch_op.drop_constraint('fk_di_raw', type_='foreignkey')
        batch_op.alter_column(
            'raw_data_id',
            existing_type=sa.Integer(),
            nullable=False,
        )
        batch_op.create_foreign_key(
            'fk_di_raw',
            'raw_data',
            ['raw_data_id'], ['id'],
            ondelete='CASCADE',
        )
