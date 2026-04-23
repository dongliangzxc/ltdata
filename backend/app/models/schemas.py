from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Numeric, Text, DateTime,
    ForeignKey, JSON
)
from sqlalchemy.orm import relationship
from pydantic import BaseModel
from app.models.database import Base


# ─────────────────────────── ORM Models ───────────────────────────

class UploadFileRecord(Base):
    __tablename__ = "upload_files"

    id = Column(Integer, primary_key=True, index=True)
    filename = Column(String(255), nullable=False)
    platform = Column(String(50))           # JD / TM / TB
    month_range = Column(String(20))        # e.g. "202507-202509"
    row_count = Column(Integer, default=0)
    status = Column(String(20), default="done")  # pending/processing/done/error
    uploaded_at = Column(DateTime, default=datetime.utcnow)

    raw_data = relationship("RawDataRecord", back_populates="file", cascade="all, delete-orphan")


class RawDataRecord(Base):
    __tablename__ = "raw_data"

    id = Column(Integer, primary_key=True, index=True)
    file_id = Column(Integer, ForeignKey("upload_files.id"), nullable=False)
    platform = Column(String(50))
    month = Column(Integer)                 # 202507
    category_lv0 = Column(String(100))
    category_lv1 = Column(String(100))
    category_lv2 = Column(String(100))
    category_lv3 = Column(String(100))
    category_lv4 = Column(String(100))
    category_lv5 = Column(String(100))
    item_id = Column(String(100))
    item_name = Column(Text)
    item_image = Column(Text)
    item_url = Column(Text)
    ref_price = Column(Numeric(12, 2))
    brand_raw = Column(String(200))
    shop_name = Column(String(200))
    sales_qty = Column(Integer)
    sales_amount = Column(Numeric(14, 2))
    price = Column(Numeric(12, 2))
    brand_std = Column(String(100))
    model_std = Column(String(100))
    extra_data = Column(JSON)
    created_at = Column(DateTime, default=datetime.utcnow)

    file = relationship("UploadFileRecord", back_populates="raw_data")


class CleanJobRecord(Base):
    __tablename__ = "clean_jobs"

    id = Column(Integer, primary_key=True, index=True)
    file_ids = Column(JSON)                 # list of file_id
    rules = Column(JSON)
    status = Column(String(20), default="done")
    row_in = Column(Integer, default=0)
    row_out = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)

    cleaned_data = relationship("CleanedDataRecord", back_populates="job", cascade="all, delete-orphan")


class CleanedDataRecord(Base):
    __tablename__ = "cleaned_data"

    id = Column(Integer, primary_key=True, index=True)
    raw_data_id = Column(Integer, ForeignKey("raw_data.id"))
    clean_job_id = Column(Integer, ForeignKey("clean_jobs.id"), nullable=False)
    platform = Column(String(50))
    month = Column(Integer)
    category_lv1 = Column(String(100))
    category_lv2 = Column(String(100))
    category_lv3 = Column(String(100))
    category_lv4 = Column(String(100))
    category_lv5 = Column(String(100))
    item_id = Column(String(100))
    item_url = Column(Text)
    item_name = Column(Text)
    item_image = Column(Text)
    ref_price = Column(Numeric(12, 2))
    brand_raw = Column(String(200))
    shop_name = Column(String(200))
    sales_qty = Column(Integer)
    sales_amount = Column(Numeric(14, 2))
    price = Column(Numeric(12, 2))
    brand_std = Column(String(100))
    model_std = Column(String(100))
    created_at = Column(DateTime, default=datetime.utcnow)

    job = relationship("CleanJobRecord", back_populates="cleaned_data")


# ─────────────────────────── Pydantic Schemas ───────────────────────────

class UploadFileOut(BaseModel):
    id: int
    filename: str
    platform: Optional[str]
    month_range: Optional[str]
    row_count: int
    status: str
    uploaded_at: datetime

    model_config = {"from_attributes": True}


class RawDataOut(BaseModel):
    id: int
    file_id: int
    platform: Optional[str]
    month: Optional[int]
    category_lv0: Optional[str]
    category_lv1: Optional[str]
    category_lv2: Optional[str]
    item_id: Optional[str]
    item_name: Optional[str]
    item_image: Optional[str]
    item_url: Optional[str]
    ref_price: Optional[float]
    brand_raw: Optional[str]
    shop_name: Optional[str]
    sales_qty: Optional[int]
    sales_amount: Optional[float]
    price: Optional[float]
    brand_std: Optional[str]
    model_std: Optional[str]

    model_config = {"from_attributes": True}


class CleanJobOut(BaseModel):
    id: int
    file_ids: list
    rules: dict
    status: str
    row_in: int
    row_out: int
    created_at: datetime

    model_config = {"from_attributes": True}


class CleanedDataOut(BaseModel):
    id: int
    clean_job_id: int
    platform: Optional[str]
    month: Optional[int]
    category_lv1: Optional[str]
    category_lv2: Optional[str]
    item_id: Optional[str]
    item_name: Optional[str]
    item_url: Optional[str]
    ref_price: Optional[float]
    brand_raw: Optional[str]
    shop_name: Optional[str]
    sales_qty: Optional[int]
    sales_amount: Optional[float]
    price: Optional[float]
    brand_std: Optional[str]
    model_std: Optional[str]

    model_config = {"from_attributes": True}


class PaginatedResponse(BaseModel):
    total: int
    page: int
    page_size: int
    items: list
