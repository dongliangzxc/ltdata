"""pending review workbench fields

Revision ID: p25a1b2c3d4e5
Revises: p24a1b2c3d4e5
Create Date: 2026-06-12
"""
from alembic import op
import sqlalchemy as sa


revision = "p25a1b2c3d4e5"
down_revision = "p24a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("match_results", sa.Column("dispute_reason", sa.String(length=500), nullable=True))
    op.add_column("match_results", sa.Column("review_note", sa.String(length=500), nullable=True))
    op.add_column("match_results", sa.Column("reviewed_at", sa.DateTime(), nullable=True))


def downgrade():
    op.drop_column("match_results", "reviewed_at")
    op.drop_column("match_results", "review_note")
    op.drop_column("match_results", "dispute_reason")
