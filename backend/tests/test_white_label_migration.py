"""p81 白牌归类迁移：建表与默认配置。"""
import importlib.util
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import create_engine, inspect, text

from app.models.schemas import Base


def test_white_label_migration_seeds_placeholder_data(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/p81a1b2c3d4e5_white_label.py"
    spec = importlib.util.spec_from_file_location("white_label_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE white_label_rules"))
        connection.execute(text("DROP TABLE white_label_policies"))
        connection.execute(text(
            "INSERT INTO categories (code, name, sort_order, created_at) VALUES "
            "('headphone', '耳机', 1, CURRENT_TIMESTAMP), "
            "('bt_speaker', '无线蓝牙音箱', 2, CURRENT_TIMESTAMP)"
        ))
        monkeypatch.setattr(migration, "op", Operations(MigrationContext.configure(connection)))
        migration.upgrade()

        policies = connection.execute(text(
            "SELECT category_code, enabled, mode, brand_code, unmatched_model_id "
            "FROM white_label_policies ORDER BY category_code"
        )).all()
        assert [row[0] for row in policies] == ["bt_speaker", "headphone"]
        assert all(row[1] == 1 and row[2] == "suggest" and row[3] == "无品牌" for row in policies)
        assert all(row[4] is not None for row in policies)

        brands = connection.execute(text(
            "SELECT brand_code FROM brands ORDER BY brand_code"
        )).all()
        assert {row[0] for row in brands} >= {"无品牌", "其他品牌"}

        models = connection.execute(text(
            "SELECT category_code, COUNT(*) FROM models WHERE brand_code = '无品牌' "
            "GROUP BY category_code ORDER BY category_code"
        )).all()
        assert dict(models) == {"bt_speaker": 6, "headphone": 8}

        rules = connection.execute(text(
            "SELECT category_code, COUNT(*) FROM white_label_rules "
            "GROUP BY category_code ORDER BY category_code"
        )).all()
        assert dict(rules) == {"bt_speaker": 7, "headphone": 10}

        # 半入耳必须优先于入耳
        half_priority = connection.execute(text(
            "SELECT r.priority FROM white_label_rules r "
            "JOIN models m ON m.id = r.model_id "
            "WHERE r.category_code = 'headphone' AND r.keyword = '半入耳'"
        )).scalar_one()
        inear_priority = connection.execute(text(
            "SELECT r.priority FROM white_label_rules r "
            "JOIN models m ON m.id = r.model_id "
            "WHERE r.category_code = 'headphone' AND r.keyword = '入耳'"
        )).scalar_one()
        assert half_priority < inear_priority

        migration.downgrade()
        assert "white_label_policies" not in inspect(connection).get_table_names()
        assert "white_label_rules" not in inspect(connection).get_table_names()
    engine.dispose()
