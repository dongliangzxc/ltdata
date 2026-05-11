"""P7 — add category_code to noise_words

Revision ID: p7a1b2c3d4e5
Revises: p4c3d4e5f6a7
Create Date: 2026-05-11
"""
from alembic import op
import sqlalchemy as sa

revision = 'p7a1b2c3d4e5'
down_revision = 'p4c3d4e5f6a7'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('noise_words',
        sa.Column('category_code', sa.String(50), nullable=True))
    op.create_index('ix_noise_words_category_code', 'noise_words', ['category_code'])


def downgrade():
    op.drop_index('ix_noise_words_category_code', table_name='noise_words')
    op.drop_column('noise_words', 'category_code')
