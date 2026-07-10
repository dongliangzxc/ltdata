from sqlalchemy import create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from app.core.config import Settings, settings


def build_engine_options(config: Settings) -> dict:
    return {
        "pool_pre_ping": True,
        "pool_size": config.DATABASE_POOL_SIZE,
        "max_overflow": config.DATABASE_MAX_OVERFLOW,
        "pool_timeout": config.DATABASE_POOL_TIMEOUT,
        "pool_recycle": config.DATABASE_POOL_RECYCLE,
    }


engine = create_engine(settings.DATABASE_URL, **build_engine_options(settings))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
