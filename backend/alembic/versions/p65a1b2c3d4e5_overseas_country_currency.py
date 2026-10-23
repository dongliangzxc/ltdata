"""countries, exchange rates and country codes for overseas data

Revision ID: p65a1b2c3d4e5
Revises: p64a1b2c3d4e5
Create Date: 2026-10-22
"""
from typing import Sequence, Union

import logging

import sqlalchemy as sa
from alembic import op
from sqlalchemy.exc import IntegrityError


logger = logging.getLogger(__name__)


revision: str = "p65a1b2c3d4e5"
down_revision: Union[str, Sequence[str], None] = "p64a1b2c3d4e5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _columns(inspector, table: str) -> set[str]:
    return {column["name"] for column in inspector.get_columns(table)}


def _indexes(inspector, table: str) -> set[str]:
    return {index["name"] for index in inspector.get_indexes(table)}


def _unique_constraints(inspector, table: str) -> set[str]:
    return {constraint["name"] for constraint in inspector.get_unique_constraints(table)}


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    # ── Country / currency master ─────────────────────────────
    if "countries" not in inspector.get_table_names():
        op.create_table(
            "countries",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("code", sa.String(length=8), nullable=False),
            sa.Column("name_cn", sa.String(length=64), nullable=False),
            sa.Column("name_en", sa.String(length=128), nullable=True),
            sa.Column("currency_code", sa.String(length=8), nullable=False),
            sa.Column("currency_symbol", sa.String(length=8), nullable=True),
            sa.Column("region", sa.String(length=16), nullable=False, server_default="overseas"),
            sa.Column("is_active", sa.SmallInteger(), nullable=False, server_default="1"),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="100"),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("code", name="uq_countries_code"),
        )
        op.create_index("ix_countries_code", "countries", ["code"], unique=False)

    if "exchange_rates" not in inspector.get_table_names():
        op.create_table(
            "exchange_rates",
            sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
            sa.Column("country_code", sa.String(length=8), nullable=False),
            sa.Column("currency_code", sa.String(length=8), nullable=False),
            sa.Column("rate_to_cny", sa.Numeric(18, 8), nullable=False),
            sa.Column("source", sa.String(length=32), nullable=False, server_default="manual"),
            sa.Column("operator", sa.String(length=100), nullable=True),
            sa.Column("remark", sa.String(length=500), nullable=True),
            sa.Column("created_at", sa.DateTime(), nullable=True),
            sa.Column("updated_at", sa.DateTime(), nullable=True),
            sa.UniqueConstraint("country_code", name="uq_fx_country"),
        )
        op.create_index("ix_exchange_rates_country_code", "exchange_rates", ["country_code"], unique=False)

    op.execute(
        "INSERT IGNORE INTO countries "
        "(code, name_cn, name_en, currency_code, currency_symbol, region, is_active, sort_order, created_at, updated_at) "
        "VALUES ('CN', '中国', 'China', 'CNY', '¥', 'domestic', 1, 0, NOW(), NOW())"
    )

    # ── Country columns ───────────────────────────────────────
    upload_columns = _columns(inspector, "upload_files")
    if "country_code" not in upload_columns:
        op.add_column("upload_files", sa.Column("country_code", sa.String(length=8), nullable=True, comment="ISO 国家码"))
    upload_indexes = _indexes(inspector, "upload_files")
    if "ix_upload_files_country_code" not in upload_indexes:
        op.create_index("ix_upload_files_country_code", "upload_files", ["country_code"], unique=False)

    raw_columns = _columns(inspector, "raw_data")
    if "country_code" not in raw_columns:
        op.add_column("raw_data", sa.Column("country_code", sa.String(length=8), nullable=True, comment="ISO 国家码"))
    raw_indexes = _indexes(inspector, "raw_data")
    if "ix_raw_data_country_code" not in raw_indexes:
        op.create_index("ix_raw_data_country_code", "raw_data", ["country_code"], unique=False)

    cleaned_columns = _columns(inspector, "cleaned_data")
    if "country_code" not in cleaned_columns:
        op.add_column("cleaned_data", sa.Column("country_code", sa.String(length=8), nullable=True, comment="ISO 国家码"))
    cleaned_indexes = _indexes(inspector, "cleaned_data")
    if "ix_cleaned_data_country_code" not in cleaned_indexes:
        op.create_index("ix_cleaned_data_country_code", "cleaned_data", ["country_code"], unique=False)

    # ── Backfill domestic legacy rows ─────────────────────────
    op.execute(
        "UPDATE upload_files SET country_code='CN' "
        "WHERE country_code IS NULL AND (data_region IS NULL OR data_region='domestic')"
    )
    op.execute(
        "UPDATE raw_data rd JOIN upload_files uf ON uf.id = rd.file_id "
        "SET rd.country_code='CN' "
        "WHERE rd.country_code IS NULL AND (uf.data_region IS NULL OR uf.data_region='domestic')"
    )
    op.execute(
        "UPDATE cleaned_data cd JOIN raw_data rd ON rd.id = cd.raw_data_id "
        "SET cd.country_code=rd.country_code WHERE cd.country_code IS NULL"
    )

    # ── Dedup key must include country ────────────────────────
    unique_constraints = _unique_constraints(inspector, "raw_data")
    raw_indexes = _indexes(inspector, "raw_data")
    desired_columns = ["country_code", "item_id", "month", "platform"]
    existing_unique = next(
        (item for item in inspector.get_unique_constraints("raw_data") if item.get("name") == "uq_raw_dedup"),
        None,
    )
    if existing_unique is not None and list(existing_unique.get("column_names") or []) == desired_columns:
        pass
    else:
        if "uq_raw_dedup" in unique_constraints:
            op.drop_constraint("uq_raw_dedup", "raw_data", type_="unique")
        elif "uq_raw_dedup" in raw_indexes:
            op.drop_index("uq_raw_dedup", table_name="raw_data")
        try:
            op.create_unique_constraint(
                "uq_raw_dedup",
                "raw_data",
                desired_columns,
            )
        except IntegrityError:
            # Production may contain legacy duplicate rows created before the
            # original unique key existed.  Do not block the deployment on a
            # historical data cleanup; application-level dedup still uses the
            # country-aware lookup below.
            logger.warning(
                "raw_data contains duplicate (country_code,item_id,month,platform) rows; "
                "skipping uq_raw_dedup creation"
            )

    raw_indexes = _indexes(inspector, "raw_data")
    if "idx_raw_dedup_lookup" in raw_indexes:
        op.drop_index("idx_raw_dedup_lookup", table_name="raw_data")
    op.create_index(
        "idx_raw_dedup_lookup",
        "raw_data",
        ["country_code", "item_id", "month", "platform"],
        unique=False,
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)

    raw_indexes = _indexes(inspector, "raw_data")
    if "idx_raw_dedup_lookup" in raw_indexes:
        op.drop_index("idx_raw_dedup_lookup", table_name="raw_data")
    op.create_index("idx_raw_dedup_lookup", "raw_data", ["item_id", "month", "platform"], unique=False)

    unique_constraints = _unique_constraints(inspector, "raw_data")
    raw_indexes = _indexes(inspector, "raw_data")
    if "uq_raw_dedup" in unique_constraints:
        op.drop_constraint("uq_raw_dedup", "raw_data", type_="unique")
    elif "uq_raw_dedup" in raw_indexes:
        op.drop_index("uq_raw_dedup", table_name="raw_data")
    try:
        op.create_unique_constraint("uq_raw_dedup", "raw_data", ["item_id", "month", "platform"])
    except IntegrityError:
        logger.warning("raw_data contains duplicate rows; skipping legacy uq_raw_dedup restore")

    for table, index_name, column_name in (
        ("cleaned_data", "ix_cleaned_data_country_code", "country_code"),
        ("raw_data", "ix_raw_data_country_code", "country_code"),
        ("upload_files", "ix_upload_files_country_code", "country_code"),
    ):
        columns = _columns(inspector, table)
        indexes = _indexes(inspector, table)
        if index_name in indexes:
            op.drop_index(index_name, table_name=table)
        if column_name in columns:
            op.drop_column(table, column_name)

    if "exchange_rates" in inspector.get_table_names():
        op.drop_table("exchange_rates")
    if "countries" in inspector.get_table_names():
        op.drop_table("countries")
