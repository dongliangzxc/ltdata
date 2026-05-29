"""rebuild historical mappings as confirmed results

Revision ID: p24a1b2c3d4e5
Revises: p23a1b2c3d4e5
Create Date: 2026-05-29
"""
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "p24a1b2c3d4e5"
down_revision = "p23a1b2c3d4e5"
branch_labels = None
depends_on = None


def upgrade():
    op.add_column("raw_data", sa.Column("week", sa.String(length=50), nullable=True))
    op.add_column("cleaned_data", sa.Column("week", sa.String(length=50), nullable=True))

    op.drop_table("historical_mappings")
    op.create_table(
        "historical_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("import_batch", sa.String(length=200), nullable=True),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=True),
        sa.Column("item_url", sa.Text(), nullable=True),
        sa.Column("item_name", sa.Text(), nullable=False),
        sa.Column("item_name_norm", sa.Text(), nullable=False),
        sa.Column("year", sa.Integer(), nullable=False),
        sa.Column("month_num", sa.Integer(), nullable=False),
        sa.Column("week", sa.String(length=50), nullable=True),
        sa.Column("month", sa.String(length=7), nullable=False),
        sa.Column("report_type", sa.String(length=100), nullable=True),
        sa.Column("channel", sa.String(length=100), nullable=True),
        sa.Column("category_name_raw", sa.String(length=200), nullable=True),
        sa.Column("category_code_raw", sa.String(length=100), nullable=True),
        sa.Column("brand_raw", sa.String(length=200), nullable=True),
        sa.Column("brand_code_raw", sa.String(length=100), nullable=True),
        sa.Column("model_text", sa.String(length=200), nullable=False),
        sa.Column("model_code_raw", sa.String(length=100), nullable=True),
        sa.Column("model_id", sa.Integer(), nullable=False),
        sa.Column("model_code", sa.String(length=100), nullable=False),
        sa.Column("category_code", sa.String(length=50), nullable=True),
        sa.Column("sales_amount", sa.Numeric(14, 2), nullable=True),
        sa.Column("sales_qty", sa.Integer(), nullable=True),
        sa.Column("price", sa.Numeric(14, 2), nullable=True),
        sa.Column("match_key_type", sa.String(length=50), nullable=False),
        sa.Column("raw_payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("idx_hist_batch", "historical_mappings", ["import_batch"])
    op.create_index("idx_hist_item_period", "historical_mappings", ["platform", "item_id", "year", "month_num", "week"])
    op.create_index("idx_hist_month", "historical_mappings", ["month"])
    op.create_index(
        "idx_hist_name_period",
        "historical_mappings",
        ["platform", "item_name_norm", "year", "month_num", "week"],
        mysql_length={"item_name_norm": 255},
    )
    op.create_index(
        "idx_hist_url_period",
        "historical_mappings",
        ["platform", "item_url", "year", "month_num", "week"],
        mysql_length={"item_url": 255},
    )


def downgrade():
    op.drop_column("cleaned_data", "week")
    op.drop_column("raw_data", "week")

    op.drop_index("idx_hist_url_period", table_name="historical_mappings")
    op.drop_index("idx_hist_name_period", table_name="historical_mappings")
    op.drop_index("idx_hist_month", table_name="historical_mappings")
    op.drop_index("idx_hist_item_period", table_name="historical_mappings")
    op.drop_index("idx_hist_batch", table_name="historical_mappings")
    op.drop_table("historical_mappings")
    op.create_table(
        "historical_mappings",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(length=50), nullable=False),
        sa.Column("item_id", sa.String(length=200), nullable=False),
        sa.Column("model_id", sa.Integer(), nullable=True),
        sa.Column("import_batch", sa.String(length=100), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("NOW()")),
        sa.ForeignKeyConstraint(["model_id"], ["models.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("platform", "item_id", name="uq_hist_platform_item"),
    )
    op.create_index("idx_hist_platform_item", "historical_mappings", ["platform", "item_id"])
    op.create_index("idx_hist_import_batch", "historical_mappings", ["import_batch"])
