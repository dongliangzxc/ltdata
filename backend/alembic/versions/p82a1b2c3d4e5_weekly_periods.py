"""Month-local weeks; keep existing rows and IDs as monthly until explicitly classified."""
import logging

from alembic import op
import sqlalchemy as sa
from sqlalchemy.engine import make_url
from app.core.config import settings

revision = "p82a1b2c3d4e5"
down_revision = "p81a1b2c3d4e5"
branch_labels = None
depends_on = None

logger = logging.getLogger(__name__)


def _analytics_schema():
    return make_url(settings.ANALYTICS_DATABASE_URL).database if op.get_bind().dialect.name == "mysql" else None


def _add_week(table, schema=None):
    if "week_of_month" not in {c["name"] for c in sa.inspect(op.get_bind()).get_columns(table, schema=schema)}:
        op.add_column(table, sa.Column("week_of_month", sa.SmallInteger(), nullable=False, server_default="0"), schema=schema)


def _replace_unique(table, name, columns, schema=None):
    existing = {item["name"]: item for item in sa.inspect(op.get_bind()).get_unique_constraints(table, schema=schema)}
    if name in existing and existing[name]["column_names"] == columns:
        return
    with op.batch_alter_table(table, schema=schema) as batch:
        if name in existing:
            batch.drop_constraint(name, type_="unique")
        batch.create_unique_constraint(name, columns)


def _add_column(table, column):
    if column.name not in {item["name"] for item in sa.inspect(op.get_bind()).get_columns(table)}:
        op.add_column(table, column)


def _index(table, name, columns):
    existing = {item["name"]: item for item in sa.inspect(op.get_bind()).get_indexes(table)}
    if name in existing and existing[name]["column_names"] == columns:
        return
    if name in existing:
        op.drop_index(name, table_name=table)
    op.create_index(name, table, columns)


def _check_legacy_duplicates(table, name, columns, schema=None, allow_legacy=False):
    inspector = sa.inspect(op.get_bind())
    if any(item["name"] == name for item in inspector.get_unique_constraints(table, schema=schema)):
        return True
    source = sa.Table(table, sa.MetaData(), schema=schema, autoload_with=op.get_bind())
    keys = [source.c[column] for column in columns]
    if "week_of_month" in source.c:
        keys.append(source.c.week_of_month)
    duplicates = sa.select(sa.func.count()).select_from(source).where(
        *(column.isnot(None) for column in keys)
    ).group_by(*keys).having(sa.func.count() > 1).limit(1)
    if op.get_bind().execute(duplicates).first():
        if allow_legacy:
            logger.warning("%s contains legacy duplicate periods; preserving rows and application-level dedup without uq_raw_dedup", table)
            return False
        raise RuntimeError(f"{table}存在未受唯一约束保护的历史重复周期，请先核对重复数据；本迁移不会删除原数据")
    return True


def upgrade():
    schema = _analytics_schema()
    published_exists = sa.inspect(op.get_bind()).has_table("published_items", schema=schema)
    raw_unique_safe = _check_legacy_duplicates("raw_data", "uq_raw_dedup", ["country_code", "item_id", "month", "platform"], allow_legacy=True)
    if published_exists:
        _check_legacy_duplicates("published_items", "uq_published_item", ["platform", "item_id", "month"], schema)
    for table in ("raw_data", "cleaned_data", "clean_jobs"):
        _add_week(table)
    _add_column("upload_files", sa.Column("period_type", sa.String(10), nullable=False, server_default="month"))
    _add_column("upload_files", sa.Column("weeks", sa.JSON(), nullable=True))
    _add_column("export_jobs", sa.Column("period_type", sa.String(10), nullable=False, server_default="month"))
    _add_column("export_jobs", sa.Column("weeks", sa.JSON(), nullable=True))
    if raw_unique_safe:
        _replace_unique("raw_data", "uq_raw_dedup", ["country_code", "item_id", "month", "platform", "week_of_month"])
    _index("raw_data", "idx_raw_dedup_lookup", ["country_code", "item_id", "month", "platform", "week_of_month"])
    _index("raw_data", "idx_raw_data_month_platform", ["month", "platform", "week_of_month"])
    _index("clean_jobs", "ix_clean_jobs_week_of_month", ["week_of_month"])
    if published_exists:
        _add_week("published_items", schema)
        _replace_unique("published_items", "uq_published_item", ["platform", "item_id", "month", "week_of_month"], schema)


def downgrade():
    schema = _analytics_schema()
    tables = [(table, None) for table in ("raw_data", "cleaned_data", "clean_jobs")]
    if sa.inspect(op.get_bind()).has_table("published_items", schema=schema):
        tables.append(("published_items", schema))
    for name, table_schema in tables:
        table = sa.Table(name, sa.MetaData(), schema=table_schema, autoload_with=op.get_bind())
        if op.get_bind().execute(sa.select(table.c.week_of_month).where(table.c.week_of_month > 0).limit(1)).first():
            raise RuntimeError("已有周度数据，禁止降回月度唯一约束；请先停止周度写入并制定数据回退方案")
    for name, table_schema in tables:
        if name == "published_items":
            _replace_unique(name, "uq_published_item", ["platform", "item_id", "month"], table_schema)
    if _check_legacy_duplicates("raw_data", "uq_raw_dedup", ["country_code", "item_id", "month", "platform"], allow_legacy=True):
        _replace_unique("raw_data", "uq_raw_dedup", ["country_code", "item_id", "month", "platform"])
    op.drop_index("idx_raw_dedup_lookup", table_name="raw_data")
    op.create_index("idx_raw_dedup_lookup", "raw_data", ["country_code", "item_id", "month", "platform"])
    op.drop_index("idx_raw_data_month_platform", table_name="raw_data")
    op.create_index("idx_raw_data_month_platform", "raw_data", ["month", "platform"])
    op.drop_index("ix_clean_jobs_week_of_month", table_name="clean_jobs")
    for name, table_schema in tables:
        with op.batch_alter_table(name, schema=table_schema) as batch:
            batch.drop_column("week_of_month")
    op.drop_column("export_jobs", "weeks")
    op.drop_column("export_jobs", "period_type")
    op.drop_column("upload_files", "weeks")
    op.drop_column("upload_files", "period_type")
