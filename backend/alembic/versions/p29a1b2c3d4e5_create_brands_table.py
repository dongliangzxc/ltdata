"""create brands table

Revision ID: p29a1b2c3d4e5
Revises: p28a1b2c3d4e5
Create Date: 2026-06-29
"""
from alembic import op
import sqlalchemy as sa


revision = "p29a1b2c3d4e5"
down_revision = "p28a1b2c3d4e5"
branch_labels = None
depends_on = None


_INVALID_BRAND_CODES = ("", "-", "--")


def upgrade() -> None:
    bind = op.get_bind()
    dialect_name = bind.dialect.name

    op.create_table(
        "brands",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("brand_code", sa.String(length=100), nullable=False),
        sa.Column("brand_name", sa.String(length=200), nullable=True),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.text("CURRENT_TIMESTAMP"),
        ),
        sa.UniqueConstraint("brand_code", name="uq_brands_brand_code"),
    )
    op.create_index("ix_brands_brand_code", "brands", ["brand_code"])

    if dialect_name == "mysql":
        bind.execute(sa.text("""
            ALTER TABLE brands
            MODIFY updated_at DATETIME NOT NULL
            DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP
        """))

    if dialect_name == "mysql":
        bind.execute(sa.text("""
            INSERT IGNORE INTO brands (brand_code, brand_name, status, created_at, updated_at)
            SELECT
                TRIM(m.brand_code) AS brand_code,
                MAX(NULLIF(TRIM(m.brand_name), '')) AS brand_name,
                'active',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM models m
            WHERE m.brand_code IS NOT NULL
              AND TRIM(m.brand_code) NOT IN ('', '-', '--')
            GROUP BY TRIM(m.brand_code)
        """))
    else:
        bind.execute(sa.text("""
            INSERT INTO brands (brand_code, brand_name, status, created_at, updated_at)
            SELECT
                TRIM(m.brand_code) AS brand_code,
                MAX(NULLIF(TRIM(m.brand_name), '')) AS brand_name,
                'active',
                CURRENT_TIMESTAMP,
                CURRENT_TIMESTAMP
            FROM models m
            WHERE m.brand_code IS NOT NULL
              AND TRIM(m.brand_code) NOT IN ('', '-', '--')
            GROUP BY TRIM(m.brand_code)
            ON CONFLICT (brand_code) DO NOTHING
        """))


def downgrade() -> None:
    op.drop_index("ix_brands_brand_code", table_name="brands")
    op.drop_table("brands")
