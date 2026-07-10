from app.core.config import Settings
from app.models.database import build_engine_options


def test_main_database_pool_options_are_configurable_and_explicit():
    settings = Settings(
        DATABASE_POOL_SIZE=21,
        DATABASE_MAX_OVERFLOW=9,
        DATABASE_POOL_TIMEOUT=12,
        DATABASE_POOL_RECYCLE=1800,
    )

    options = build_engine_options(settings)

    assert options["pool_size"] == 21
    assert options["max_overflow"] == 9
    assert options["pool_timeout"] == 12
    assert options["pool_recycle"] == 1800
    assert options["pool_pre_ping"] is True


def test_main_database_pool_defaults_raise_capacity_above_sqlalchemy_defaults():
    options = build_engine_options(Settings())

    assert options["pool_size"] > 5
    assert options["max_overflow"] > 10
