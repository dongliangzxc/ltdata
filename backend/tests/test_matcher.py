"""
matcher.py 单元测试
使用内存 SQLite，不依赖 MySQL。
"""
import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from app.models.database import Base
from app.models.schemas import (
    ModelRecord, MatchResult, CleanedDataRecord, CleanJobRecord,
    UploadFileRecord, RawDataRecord,
)
from app.services.matcher import run_match


@pytest.fixture
def db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
    )
    # SQLite 不支持 ON UPDATE，屏蔽警告
    @event.listens_for(engine, "connect")
    def set_sqlite_pragma(conn, _):
        conn.execute("PRAGMA foreign_keys=ON")

    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    yield session
    session.close()


def _seed(db, *, brand_code, model_code, brand_name=None, model_name=None, category_name="TEST"):
    """向 db 插入一条 ModelRecord，返回该记录。"""
    m = ModelRecord(
        brand_code=brand_code,
        model_code=model_code,
        brand_name=brand_name or brand_code,
        model_name=model_name or model_code,
        category_name=category_name,
    )
    db.add(m)
    db.flush()
    return m


def _seed_clean_row(db, *, brand_raw, item_name):
    """插入 UploadFileRecord + RawDataRecord + CleanJobRecord + CleanedDataRecord，返回 clean_job_id。"""
    # 创建 FK 父级记录
    upload = UploadFileRecord(filename="test.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    raw = RawDataRecord(file_id=upload.id, item_name=item_name, brand_raw=brand_raw)
    db.add(raw)
    db.flush()

    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    row = CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=job.id,
        brand_raw=brand_raw,
        item_name=item_name,
    )
    db.add(row)
    db.flush()
    return job.id


# ── 核心回归测试 ────────────────────────────────────────────────

def test_brand_matched_but_no_model_should_be_pending(db):
    """品牌识别到但所有型号都不在商品名中 → pending，不应跨品牌误匹配。"""
    # EDIFIER 品牌，型号 B1/B2/G7000，均不在商品名里
    _seed(db, brand_code="EDIFIER", model_code="B1")
    _seed(db, brand_code="EDIFIER", model_code="B2")
    _seed(db, brand_code="EDIFIER", model_code="G7000")
    # 另一品牌有 5 字符型号，不能被误匹配
    _seed(db, brand_code="OTHER", model_code="HALO1")

    item_name = "漫步者 EDIFIERHalo Soundbar桌面蓝牙音箱游戏电脑音响"
    clean_job_id = _seed_clean_row(db, brand_raw="漫步者", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result is not None
    assert result.match_status == "pending", (
        f"期望 pending，实际 {result.match_status}，model_id={result.model_id}"
    )
    assert result.model_id is None


def test_model_code_in_item_name_should_match(db):
    """model_code 出现在商品名中 → matched，match_source=s1。"""
    _seed(db, brand_code="EDIFIER", model_code="G7000", brand_name="漫步者")
    item_name = "漫步者 EDIFIER G7000 回音壁"
    clean_job_id = _seed_clean_row(db, brand_raw="漫步者", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched"
    assert result.match_source == "s1"
    assert result.model_id is not None


def test_s4_fires_when_no_brand_identified(db):
    """无品牌线索时，S4 长码兜底应生效。"""
    _seed(db, brand_code="UNKNOWN", model_code="HALO1X", brand_name="unknown_brand")
    # 商品名不含任何品牌，但含有 5+ 字符型号码
    item_name = "某款 HALO1X 蓝牙音箱"
    clean_job_id = _seed_clean_row(db, brand_raw=None, item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched"
    assert result.match_source == "s4"


def test_match_source_s2(db):
    """brand_code 出现在 item_name 中（不在 brand_raw 中）→ match_source=s2。"""
    _seed(db, brand_code="PHILIPS", model_code="HTL3320", brand_name="飞利浦")
    # brand_raw 为空，item_name 含 brand_code "PHILIPS" 和型号 "HTL3320"
    item_name = "飞利浦 PHILIPS HTL3320 回音壁"
    clean_job_id = _seed_clean_row(db, brand_raw=None, item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched"
    assert result.match_source == "s2"


from app.models.schemas import ModelAlias


def test_alias_match_within_brand(db):
    """别名出现在 item_name 中，应命中对应型号（品牌内匹配）。"""
    m = _seed(db, brand_code="EDIFIER", brand_name="漫步者", model_code="B2-PRO")
    alias = ModelAlias(model_id=m.id, alias_code="B2PRO")
    db.add(alias)

    item_name = "漫步者 EDIFIER B2PRO 回音壁蓝牙音箱"
    clean_job_id = _seed_clean_row(db, brand_raw="漫步者", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "matched", f"期望 matched，实际 {result.match_status}"
    assert result.model_id == m.id


def test_alias_not_cross_brand(db):
    """别名不跨品牌匹配：品牌B的商品不应命中品牌A的别名。"""
    m_a = _seed(db, brand_code="BRAND_A", brand_name="品牌A", model_code="X100")
    alias = ModelAlias(model_id=m_a.id, alias_code="X100ALIAS")
    db.add(alias)

    _seed(db, brand_code="BRAND_B", brand_name="品牌B", model_code="Y200")
    item_name = "品牌B BRAND_B X100ALIAS 音箱"
    clean_job_id = _seed_clean_row(db, brand_raw="品牌B", item_name=item_name)
    db.commit()

    run_match(db, clean_job_id)

    result = db.query(MatchResult).filter(MatchResult.clean_job_id == clean_job_id).first()
    assert result.match_status == "pending", f"期望 pending，实际 {result.match_status}"
