"""Verify old uploads remain readable when adding original storage references."""
import importlib.util
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text


def test_storage_migration_preserves_legacy_records_and_guards_references(monkeypatch):
    migration_path = Path(__file__).resolve().parents[1] / "alembic/versions/p79a1b2c3d4e5_upload_stored_filename.py"
    spec = importlib.util.spec_from_file_location("upload_storage_migration", migration_path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE upload_files (id INTEGER PRIMARY KEY, filename VARCHAR(255) NOT NULL)"))
        connection.execute(text("INSERT INTO upload_files (filename) VALUES ('data.csv')"))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()
        assert connection.execute(text("SELECT filename, stored_filename FROM upload_files")).one() == ("data.csv", None)
        connection.execute(text("UPDATE upload_files SET stored_filename = 'unique.csv'"))
        with pytest.raises(RuntimeError, match="不能删除存储引用"):
            migration.downgrade()
        assert "stored_filename" in {column["name"] for column in inspect(connection).get_columns("upload_files")}
        connection.execute(text("UPDATE upload_files SET stored_filename = NULL"))
        migration.downgrade()
        assert "stored_filename" not in {column["name"] for column in inspect(connection).get_columns("upload_files")}
        assert connection.execute(text("SELECT filename FROM upload_files")).scalar_one() == "data.csv"
    engine.dispose()
