from sqlalchemy import create_engine, Column, Integer, String, Text, Numeric, DateTime, UniqueConstraint
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from datetime import datetime
from app.core.config import settings

analytics_engine = create_engine(settings.ANALYTICS_DATABASE_URL, pool_pre_ping=True, pool_recycle=3600)
AnalyticsSession = sessionmaker(autocommit=False, autoflush=False, bind=analytics_engine)
AnalyticsBase = declarative_base()


def get_analytics_db():
    db = AnalyticsSession()
    try:
        yield db
    finally:
        db.close()


# ─────────────────────────── Analytics ORM ───────────────────────────

class PublishedItem(AnalyticsBase):
    __tablename__ = "published_items"
    __table_args__ = (
        UniqueConstraint("platform", "item_id", "month", name="uq_published_item"),
    )

    id                = Column(Integer, primary_key=True, index=True)
    publish_job_id    = Column(Integer, nullable=False)
    clean_job_id      = Column(Integer, nullable=False)
    match_result_id   = Column(Integer, nullable=False)
    platform          = Column(String(50))
    month             = Column(Integer)
    category_lv1      = Column(String(100))
    category_lv2      = Column(String(100))
    category_lv3      = Column(String(100))
    category_lv4      = Column(String(100))
    category_lv5      = Column(String(100))
    item_id           = Column(String(100))
    item_name         = Column(Text)
    item_image        = Column(Text)
    item_url          = Column(Text)
    ref_price         = Column(Numeric(12, 2))
    shop_name         = Column(String(200))
    sales_qty         = Column(Integer)
    sales_amount      = Column(Numeric(14, 2))
    price             = Column(Numeric(12, 2))
    brand_code        = Column(String(100))
    brand_name        = Column(String(200))
    model_code        = Column(String(100))
    model_name        = Column(String(200))
    category_name     = Column(String(200))
    published_at      = Column(DateTime, default=datetime.utcnow)


class PublishedItemSpec(AnalyticsBase):
    __tablename__ = "published_item_specs"

    id                = Column(Integer, primary_key=True, index=True)
    published_item_id = Column(Integer, nullable=False)
    spec_name         = Column(String(200), nullable=False)
    spec_value        = Column(Text)
