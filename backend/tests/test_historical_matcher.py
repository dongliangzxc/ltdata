"""
S0.2 历史库匹配阶段单元测试
使用内存 SQLite，不依赖 MySQL。
"""
from app.models.schemas import (
    UploadFileRecord, RawDataRecord, CleanJobRecord, CleanedDataRecord,
    ModelRecord, MatchResult, HistoricalMapping, ItemUrlMapping,
)
from app.services.matcher import run_match


def _seed(db, *, platform="jd", item_id="12345", item_name="Sony HT-A7000 soundbar"):
    """创建最小可运行的 upload/raw/clean/model 数据，返回 (clean_job_id, model_id)"""
    upload = UploadFileRecord(filename="t.xlsx", status="done", row_count=1)
    db.add(upload)
    db.flush()
    raw = RawDataRecord(
        file_id=upload.id,
        platform=platform,
        item_id=item_id,
        item_name=item_name,
        brand_raw="SONY",
    )
    db.add(raw)
    db.flush()
    job = CleanJobRecord(file_ids=[upload.id], rules={}, status="done", row_in=1, row_out=1)
    db.add(job)
    db.flush()
    cleaned = CleanedDataRecord(
        raw_data_id=raw.id,
        clean_job_id=job.id,
        platform=platform,
        item_id=item_id,
        item_name=item_name,
        brand_raw="SONY",
    )
    db.add(cleaned)
    db.flush()
    model = ModelRecord(
        brand_code="SONY",
        model_code=f"MODEL-{item_id}",
        category_code="soundbar",
    )
    db.add(model)
    db.flush()
    return job.id, model.id


def test_s02_matches_by_platform_item_id(db):
    """historical_mappings 中有 (platform, item_id) → S0.2 命中，match_source='historical'"""
    job_id, model_id = _seed(db, platform="jd", item_id="99999")
    db.add(HistoricalMapping(platform="jd", item_id="99999", model_id=model_id, import_batch="batch1"))
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr is not None
    assert mr.match_source == "historical"
    assert mr.match_status == "matched"
    assert mr.model_id == model_id


def test_s02_no_match_when_not_in_table(db):
    """historical_mappings 为空时，S0.2 不命中，走后续阶段（pending）"""
    job_id, _ = _seed(db, platform="jd", item_id="88888", item_name="unknown brand XYZ no match")
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr is not None
    assert mr.match_source != "historical"
    assert mr.match_status == "pending"


def test_s0_takes_precedence_over_s02(db):
    """同一商品既有 url_mapping(S0) 又有 historical_mapping(S0.2) → S0 优先"""
    job_id, model_id = _seed(db, platform="jd", item_id="77777",
                              item_name="Sony HT-A3000 from url test")
    # 给 cleaned_data 添加 item_url，使 S0 能从 URL 提取到 (jd, 77777)
    cleaned = db.query(CleanedDataRecord).filter(CleanedDataRecord.clean_job_id == job_id).first()
    cleaned.item_url = "https://item.jd.com/77777.html"
    db.flush()
    # S0: url mapping → 另一个 model
    model2 = ModelRecord(brand_code="SONY", model_code="MODEL-URL", category_code="soundbar")
    db.add(model2)
    db.flush()
    db.add(ItemUrlMapping(platform="jd", item_id="77777", model_id=model2.id))
    # S0.2: historical mapping → model_id
    db.add(HistoricalMapping(platform="jd", item_id="77777", model_id=model_id, import_batch="b1"))
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "s0"
    assert mr.model_id == model2.id


def test_s02_platform_case_insensitive(db):
    """historical_mappings 中 platform 为小写，cleaned_data platform 大写也能命中"""
    job_id, model_id = _seed(db, platform="JD", item_id="66666")
    db.add(HistoricalMapping(platform="jd", item_id="66666", model_id=model_id, import_batch="b1"))
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr.match_source == "historical"


def test_s02_skips_when_item_id_is_none(db):
    """item_id 为 None 时，S0.2 不崩溃也不匹配"""
    job_id, model_id = _seed(db, platform="jd", item_id="55555")
    # Patch the cleaned record's item_id to None after seeding
    cleaned = db.query(CleanedDataRecord).filter(CleanedDataRecord.clean_job_id == job_id).first()
    cleaned.item_id = None
    db.add(HistoricalMapping(platform="jd", item_id="55555", model_id=model_id, import_batch="b1"))
    db.commit()

    run_match(db, job_id)

    mr = db.query(MatchResult).filter(MatchResult.clean_job_id == job_id).first()
    assert mr is not None
    assert mr.match_source != "historical"
    assert mr.match_source in ("s1", "s2", "s3", "s4", None)


def test_import_null_model_code_is_accepted(db):
    """model_code 为空时，historical_mapping 写入 model_id=None，不报 error"""
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from app.api.historical_api import router as historical_router
    from app.models.database import get_db
    import io, openpyxl

    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["platform", "item_id", "model_code"])
    ws.append(["jd", "ITEM-NULL-001", ""])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    def override_db():
        yield db

    test_app = FastAPI()
    test_app.include_router(historical_router)
    test_app.dependency_overrides[get_db] = override_db
    client = TestClient(test_app)
    resp = client.post(
        "/api/historical/import",
        files={"file": ("test.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
    )

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] == 1
    assert data.get("imported_no_model", 0) == 1
    assert data["errors"] == []

    mapping = db.query(HistoricalMapping).filter_by(platform="jd", item_id="ITEM-NULL-001").first()
    assert mapping is not None
    assert mapping.model_id is None
