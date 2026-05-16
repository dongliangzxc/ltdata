"""P12: add workbench_export_jobs and upload_confirm_jobs tables

Revision ID: p12a1b2c3d4e5
Revises: p11a1b2c3d4e5
Create Date: 2026-05-16
"""
from alembic import op
import sqlalchemy as sa

revision = 'p12a1b2c3d4e5'
down_revision = 'p11a1b2c3d4e5'
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        'workbench_export_jobs',
        sa.Column('id',          sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('status',      sa.String(20),    nullable=False, server_default='pending'),
        sa.Column('progress',    sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('file_token',  sa.String(64),    nullable=True),
        sa.Column('filename',    sa.String(500),   nullable=True),
        sa.Column('error_msg',   sa.Text(),        nullable=True),
        sa.Column('created_at',  sa.DateTime(),    nullable=True),
        sa.Column('finished_at', sa.DateTime(),    nullable=True),
    )
    op.create_table(
        'upload_confirm_jobs',
        sa.Column('id',          sa.Integer(),     primary_key=True, autoincrement=True),
        sa.Column('file_id',     sa.Integer(),     nullable=True),
        sa.Column('status',      sa.String(20),    nullable=False, server_default='pending'),
        sa.Column('progress',    sa.SmallInteger(), nullable=False, server_default='0'),
        sa.Column('result_data', sa.JSON(),        nullable=True),
        sa.Column('error_msg',   sa.Text(),        nullable=True),
        sa.Column('created_at',  sa.DateTime(),    nullable=True),
        sa.Column('finished_at', sa.DateTime(),    nullable=True),
    )


def downgrade() -> None:
    op.drop_table('upload_confirm_jobs')
    op.drop_table('workbench_export_jobs')
