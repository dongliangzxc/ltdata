from datetime import datetime
from typing import Optional
from sqlalchemy import (
    Column, Integer, String, Numeric, Text, DateTime,
    ForeignKey, JSON, SmallInteger, UniqueConstraint, CheckConstraint, Enum
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
    row_filtered = Column(Integer, default=0)
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
    model_std              = Column(String(100))
    category_lv0           = Column(String(100))
    calc_price             = Column(Numeric(12, 2))
    corrected_sales_qty    = Column(Integer)
    corrected_sales_amount = Column(Numeric(14, 2))
    created_at             = Column(DateTime, default=datetime.utcnow)
    is_recovered           = Column(SmallInteger, default=0)

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
    row_filtered: int = 0
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


# ─────────────────────────── 品类 ───────────────────────────

class Category(Base):
    __tablename__ = "categories"

    id         = Column(Integer, primary_key=True, index=True)
    code       = Column(String(50),  nullable=False, unique=True)
    name       = Column(String(100), nullable=False)
    created_at = Column(DateTime, default=datetime.utcnow)


class CategoryOut(BaseModel):
    id:         int
    code:       str
    name:       str
    created_at: datetime

    model_config = {"from_attributes": True}


class CategoryCreate(BaseModel):
    code: str
    name: str


# ─────────────────────────── 元数据规格 ───────────────────────────

class MetadataSpec(Base):
    __tablename__ = "metadata_specs"
    __table_args__ = (
        UniqueConstraint("category_code", "spec_name", name="uq_category_spec"),
    )

    id             = Column(Integer, primary_key=True, index=True)
    category_code  = Column(String(100), nullable=False)
    spec_name      = Column(String(200), nullable=False)
    spec_type      = Column(String(50),  nullable=False)
    spec_values    = Column(Text)                         # 逗号分隔
    required       = Column(Integer, default=0)           # 0/1
    decimal_places = Column(Integer, default=None)
    single_select  = Column(Integer, default=1)           # 0/1
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at     = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MetadataSpecIn(BaseModel):
    category_code:  str
    spec_name:      str
    spec_type:      str
    spec_values:    Optional[str] = None
    required:       bool = False
    decimal_places: Optional[int] = None
    single_select:  bool = True


class MetadataSpecOut(BaseModel):
    id:             int
    category_code:  str
    spec_name:      str
    spec_type:      str
    spec_values:    Optional[str]
    required:       bool
    decimal_places: Optional[int]
    single_select:  bool
    created_at:     datetime
    updated_at:     datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── 型号主信息 ───────────────────────────

class ModelRecord(Base):
    __tablename__ = "models"
    __table_args__ = (
        UniqueConstraint("brand_code", "model_code", name="uq_model"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    brand_code    = Column(String(100), nullable=False)
    model_code    = Column(String(100), nullable=False)
    category_code = Column(String(50), ForeignKey("categories.code", ondelete="SET NULL"), nullable=True)
    brand_name    = Column(String(200))
    model_name    = Column(String(200))
    launch_year   = Column(Integer)
    launch_month  = Column(Integer)
    launch_week   = Column(Integer)
    launch_price  = Column(Numeric(12, 2))
    url           = Column(Text)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    specs   = relationship("ModelSpec",  back_populates="model", cascade="all, delete-orphan")
    aliases = relationship("ModelAlias", back_populates="model", cascade="all, delete-orphan")


class ModelSpec(Base):
    __tablename__ = "model_specs"

    id         = Column(Integer, primary_key=True, index=True)
    model_id   = Column(Integer, ForeignKey("models.id"), nullable=False)
    spec_name  = Column(String(200), nullable=False)
    spec_value = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    model = relationship("ModelRecord", back_populates="specs")


class ModelAlias(Base):
    __tablename__ = "model_aliases"

    id         = Column(Integer, primary_key=True, index=True)
    model_id   = Column(Integer, ForeignKey("models.id", ondelete="CASCADE"), nullable=False)
    alias_code = Column(String(200), nullable=False, unique=True)
    created_at = Column(DateTime, default=datetime.utcnow)

    model = relationship("ModelRecord", back_populates="aliases")


class ModelSpecIn(BaseModel):
    spec_name:  str
    spec_value: Optional[str] = None


class ModelSpecOut(BaseModel):
    id:         int
    spec_name:  str
    spec_value: Optional[str]

    model_config = {"from_attributes": True}


class ModelAliasOut(BaseModel):
    id:         int
    alias_code: str

    model_config = {"from_attributes": True}


class ItemUrlMapping(Base):
    __tablename__ = "item_url_mappings"
    __table_args__ = (UniqueConstraint("platform", "item_id", name="uq_platform_item"),)

    id         = Column(Integer, primary_key=True, autoincrement=True)
    platform   = Column(String(20), nullable=False)
    item_id    = Column(String(100), nullable=False)
    item_url   = Column(String(500), nullable=True)
    model_id   = Column(Integer, ForeignKey("models.id"), nullable=False)
    price      = Column(Numeric(10, 2), nullable=True)
    created_at = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at = Column(DateTime, nullable=False, default=datetime.utcnow,
                        onupdate=datetime.utcnow)

    model = relationship("ModelRecord")


class HistoricalMapping(Base):
    __tablename__ = "historical_mappings"
    __table_args__ = (
        UniqueConstraint("platform", "item_id", name="uq_hist_platform_item"),
    )

    id           = Column(Integer, primary_key=True, index=True)
    platform     = Column(String(50),  nullable=False)
    item_id      = Column(String(200), nullable=False)
    model_id     = Column(Integer, ForeignKey("models.id"), nullable=False)
    import_batch = Column(String(100), nullable=True)
    created_at   = Column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at   = Column(DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow)

    model = relationship("ModelRecord")


class ItemUrlMappingIn(BaseModel):

    platform: str
    item_id:  str
    item_url: Optional[str] = None
    model_id: int
    price:    Optional[float] = None


class ItemUrlMappingOut(BaseModel):
    id:         int
    platform:   str
    item_id:    str
    item_url:   Optional[str] = None
    model_id:   int
    price:      Optional[float]
    brand_code: Optional[str] = None
    model_code: Optional[str] = None
    brand_name: Optional[str] = None
    model_name: Optional[str] = None
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── 规则引擎 ───────────────────────────

class NoiseWord(Base):
    __tablename__ = "noise_words"
    __table_args__ = (
        UniqueConstraint("keyword", "match_field", name="uq_noise_keyword_field"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    keyword     = Column(String(200), nullable=False)
    match_field = Column(String(20),  default="item_name")  # item_name/shop_name/brand_raw
    is_active   = Column(SmallInteger, default=1)
    created_by  = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)


class FilteredItem(Base):
    __tablename__ = "filtered_items"

    id              = Column(Integer, primary_key=True, index=True)
    raw_data_id     = Column(Integer, ForeignKey("raw_data.id"))
    clean_job_id    = Column(Integer, ForeignKey("clean_jobs.id"))
    matched_keyword = Column(String(200))
    is_recovered    = Column(SmallInteger, default=0)
    recovered_at    = Column(DateTime)
    created_at      = Column(DateTime, default=datetime.utcnow)


class BrandAlias(Base):
    __tablename__ = "brand_aliases"

    id          = Column(Integer, primary_key=True, index=True)
    alias_name  = Column(String(200), nullable=False, unique=True)
    brand_code  = Column(String(100), nullable=False)
    is_active   = Column(SmallInteger, default=1)
    created_by  = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)


class MatchRule(Base):
    __tablename__ = "match_rules"
    __table_args__ = (
        CheckConstraint("match_type IN ('contains', 'exact')", name="ck_match_rule_type"),
    )

    id          = Column(Integer, primary_key=True, index=True)
    keyword     = Column(String(200), nullable=False, unique=True)
    match_type  = Column(String(20),  default="contains")  # contains/exact
    model_id    = Column(Integer, ForeignKey("models.id"), nullable=False)
    priority    = Column(Integer, default=100)
    is_active   = Column(SmallInteger, default=1)
    created_by  = Column(String(50))
    created_at  = Column(DateTime, default=datetime.utcnow)


class AttrRule(Base):
    __tablename__ = "attr_rules"
    __table_args__ = (
        UniqueConstraint("keyword", "attr_name", "category_code", name="uq_attr_rule"),
        CheckConstraint("match_type IN ('contains', 'exact')", name="ck_attr_rule_type"),
    )

    id            = Column(Integer, primary_key=True, index=True)
    keyword       = Column(String(200), nullable=False)
    match_type    = Column(String(20),  default="contains")   # contains / exact
    attr_name     = Column(String(100), nullable=False)
    attr_value    = Column(String(200), nullable=False)
    category_code = Column(String(100), nullable=True)        # NULL = 全局生效
    priority      = Column(Integer,     default=100)
    is_active     = Column(SmallInteger, default=1)
    created_by    = Column(String(50))
    created_at    = Column(DateTime, default=datetime.utcnow)


# ─────────────────────────── 型号匹配结果 ───────────────────────────

class MatchResult(Base):
    __tablename__ = "match_results"

    id           = Column(Integer, primary_key=True, index=True)
    clean_job_id = Column(Integer, nullable=False)
    raw_data_id  = Column(Integer, nullable=False)
    model_id     = Column(Integer)
    match_status = Column(String(20), default="pending")  # matched/pending/confirmed/excluded
    matched_by   = Column(String(20), default="auto")     # auto/manual
    match_source   = Column(String(20), nullable=True)      # s0/s0.2/s0.5/historical/s1/s2/s3/s4/manual
    is_disabled    = Column(SmallInteger, nullable=False, default=0)
    disable_reason = Column(String(100), nullable=True)
    brand_identified = Column(SmallInteger, default=1)
    created_at     = Column(DateTime, default=datetime.utcnow)
    updated_at   = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class MatchResultAttr(Base):
    __tablename__ = "match_result_attrs"
    __table_args__ = (
        UniqueConstraint("match_result_id", "attr_name", name="uq_mr_attr_name"),
    )

    id               = Column(Integer, primary_key=True, index=True)
    match_result_id  = Column(Integer, ForeignKey("match_results.id"), nullable=False)
    attr_name        = Column(String(100), nullable=False)
    attr_value       = Column(String(200), nullable=False)
    rule_id          = Column(Integer, ForeignKey("attr_rules.id"), nullable=True)
    created_at       = Column(DateTime, default=datetime.utcnow)


class MatchResultOut(BaseModel):
    id:           int
    clean_job_id: int
    raw_data_id:  int
    model_id:     Optional[int]
    match_status: str
    matched_by:   str
    match_source: Optional[str] = None
    is_disabled:    int = 0
    disable_reason: Optional[str] = None
    brand_identified: int = 1
    # 关联字段（join 查询后填充）
    item_name:     Optional[str] = None
    item_url:      Optional[str] = None
    brand_raw:     Optional[str] = None
    model_code:    Optional[str] = None
    brand_code:    Optional[str] = None
    attr_count:    int = 0
    sales_qty:     Optional[int] = None
    category_name: Optional[str] = None

    model_config = {"from_attributes": True}


class MatchSummary(BaseModel):
    clean_job_id: int
    total:       int
    url_matched: int = 0
    matched:     int
    text_only:   int = 0
    pending:     int
    confirmed:   int
    excluded:    int
    disabled:    int = 0
    unidentified_brand: int = 0
    missing_attrs: int = 0


# ─────────────────────────── 发布任务 ───────────────────────────

class PublishJob(Base):
    __tablename__ = "publish_jobs"

    id              = Column(Integer, primary_key=True, index=True)
    clean_job_id    = Column(Integer, nullable=False)
    status          = Column(String(20), default="done")
    published_count = Column(Integer, default=0)
    note            = Column(String(500))
    created_at      = Column(DateTime, default=datetime.utcnow)


class PublishJobOut(BaseModel):
    id:              int
    clean_job_id:    int
    status:          str
    published_count: int
    note:            Optional[str]
    created_at:      datetime

    model_config = {"from_attributes": True}


class ModelIn(BaseModel):
    brand_code:    str
    model_code:    str
    category_code: Optional[str] = None
    brand_name:    Optional[str] = None
    model_name:    Optional[str] = None
    launch_year:   Optional[int] = None
    launch_month:  Optional[int] = None
    launch_week:   Optional[int] = None
    launch_price:  Optional[float] = None
    url:           Optional[str] = None
    specs:         list[ModelSpecIn] = []


class ModelOut(BaseModel):
    id:            int
    brand_code:    str
    model_code:    str
    category_code: Optional[str]
    category_name: Optional[str] = None   # JOIN 后填充，API 返回用
    brand_name:    Optional[str]
    model_name:    Optional[str]
    launch_year:   Optional[int]
    launch_month:  Optional[int]
    launch_week:   Optional[int]
    launch_price:  Optional[float]
    url:           Optional[str]
    specs:         list[ModelSpecOut] = []
    aliases:       list[ModelAliasOut] = []
    created_at:    datetime
    updated_at:    datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── 导出任务 ───────────────────────────

class AttrRuleIn(BaseModel):
    keyword:       str
    match_type:    str = "contains"
    attr_name:     str
    attr_value:    str
    category_code: Optional[str] = None
    priority:      int = 100


class AttrRuleOut(BaseModel):
    id:            int
    keyword:       str
    match_type:    str
    attr_name:     str
    attr_value:    str
    category_code: Optional[str]
    priority:      int
    is_active:     int
    created_at:    datetime

    model_config = {"from_attributes": True}


class MatchResultAttrOut(BaseModel):
    id:              int
    match_result_id: int
    attr_name:       str
    attr_value:      str
    rule_id:         Optional[int]

    model_config = {"from_attributes": True}


class ExportJob(Base):
    __tablename__ = "export_jobs"

    id               = Column(Integer, primary_key=True, index=True)
    clean_job_id     = Column(Integer, nullable=False)
    filename_prefix  = Column(String(255), nullable=False, default="已处理数据")
    status           = Column(String(20), default="pending")   # pending/running/done/error
    filename         = Column(String(500))
    token            = Column(String(64))
    rows             = Column(Integer)
    pending_rows     = Column(Integer)
    error_msg        = Column(Text)
    created_at       = Column(DateTime, default=datetime.utcnow)
    updated_at       = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class ExportJobOut(BaseModel):
    id:              int
    clean_job_id:    int
    filename_prefix: str
    status:          str
    filename:        Optional[str]
    token:           Optional[str]
    rows:            Optional[int]
    pending_rows:    Optional[int]
    error_msg:       Optional[str]
    created_at:      datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── 用户（登录） ───────────────────────────

class User(Base):
    __tablename__ = "users"

    id              = Column(Integer, primary_key=True, index=True)
    username        = Column(String(100), nullable=False, unique=True)
    hashed_password = Column(String(200), nullable=False)
    is_active       = Column(SmallInteger, default=1)
    created_at      = Column(DateTime, default=datetime.utcnow)


class UserOut(BaseModel):
    id:         int
    username:   str
    is_active:  int
    created_at: datetime

    model_config = {"from_attributes": True}


# ─────────────────────────── 校正规则 ───────────────────────────

class CorrectionRule(Base):
    __tablename__ = "correction_rules"

    id            = Column(Integer, primary_key=True, index=True)
    name          = Column(String(100), nullable=False)
    category_code = Column(String(100))
    brand_code    = Column(String(100))
    model_id      = Column(Integer)
    attr_name     = Column(String(200))
    attr_value    = Column(String(200))
    target        = Column(Enum('sales_qty', 'sales_amount', 'both', name='correction_target'), nullable=False)
    rule_type     = Column(Enum('multiply', 'offset', name='correction_rule_type'), nullable=False)
    value         = Column(Numeric(12, 4), nullable=False)
    priority      = Column(Integer, nullable=False, default=100)
    is_active     = Column(SmallInteger, nullable=False, default=1)
    created_at    = Column(DateTime, default=datetime.utcnow)
    updated_at    = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CorrectionRuleIn(BaseModel):
    name:          str
    category_code: Optional[str] = None
    brand_code:    Optional[str] = None
    model_id:      Optional[int] = None
    attr_name:     Optional[str] = None
    attr_value:    Optional[str] = None
    target:        str  # 'sales_qty' | 'sales_amount' | 'both'
    rule_type:     str  # 'multiply' | 'offset'
    value:         float
    priority:      int = 100
    is_active:     int = 1


class CorrectionRuleOut(CorrectionRuleIn):
    id: int
    created_at: Optional[datetime] = None

    model_config = {"from_attributes": True}
