"""历史库管理 API
- POST   /api/historical/import           Excel 导入历史确认结果（upsert）
- GET    /api/historical/batches          查询所有批次名称列表
- GET    /api/historical/mappings         分页查询映射（platform / import_batch 筛选）
- DELETE /api/historical/mappings/batch   按批次批量删除（静态路由，必须在 /{id} 之前）
- DELETE /api/historical/mappings/{id}    删除单条映射
"""
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile
from pydantic import BaseModel
from sqlalchemy import func, or_, tuple_
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import HistoricalMapping, ModelRecord
from app.utils.url_utils import extract_item_id

router = APIRouter(prefix="/api/historical", tags=["historical"])


class BatchDeleteIn(BaseModel):
    import_batch: str


def _clean_value(value) -> Optional[str]:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip()
    if not text:
        return None
    if text.lower() == "nan":
        return None
    if text.endswith(".0"):
        try:
            return str(int(float(text)))
        except ValueError:
            return text
    return text


def _clean_int(value) -> Optional[int]:
    text = _clean_value(value)
    if text is None:
        return None
    try:
        number = Decimal(text)
    except (InvalidOperation, ValueError):
        return None
    if number != number.to_integral_value():
        return None
    return int(number)


def _clean_decimal(value) -> Optional[Decimal]:
    text = _clean_value(value)
    if text is None:
        return None
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def _normalize_platform(value: Optional[str]) -> Optional[str]:
    text = _clean_value(value)
    return text.lower() if text else None


def _normalize_item_name(value: Optional[str]) -> Optional[str]:
    text = _clean_value(value)
    return " ".join(text.upper().split()) if text else None


def _get(row: dict, key: str):
    return row.get(key)


def _resolve_model(
    *,
    model_code_raw: Optional[str],
    model_text: Optional[str],
    brand_code_raw: Optional[str],
    models_by_code: dict[str, ModelRecord],
    models_by_name: dict[str, list[ModelRecord]],
):
    if model_code_raw:
        model = models_by_code.get(model_code_raw)
        if model:
            return model, None
        if not model_text:
            return None, f"型号码「{model_code_raw}」在型号库中不存在"

    if not model_text:
        return None, None

    model_by_code = models_by_code.get(model_text)
    if model_by_code:
        return model_by_code, None

    models_by_name_list = models_by_name.get(model_text, [])
    if len(models_by_name_list) == 1:
        return models_by_name_list[0], None
    if len(models_by_name_list) > 1:
        if brand_code_raw:
            matched = [m for m in models_by_name_list if m.brand_code == brand_code_raw]
            if len(matched) == 1:
                return matched[0], None
        return None, f"型号名称「{model_text}」匹配到多个型号，请填写型号码"

    return None, f"型号「{model_text}」在型号库中不存在"


def _match_key_type(item_id: Optional[str], item_url: Optional[str], item_name_norm: str) -> str:
    if item_id:
        return "item_id"
    if item_url:
        return "item_url"
    return "item_name"


def _period_filter(query, *, year: int, month_num: int, week: Optional[str]):
    query = query.filter(
        HistoricalMapping.year == year,
        HistoricalMapping.month_num == month_num,
    )
    if week:
        query = query.filter(HistoricalMapping.week == week)
    else:
        query = query.filter(HistoricalMapping.week.is_(None))
    return query


def _history_identity_key(
    *,
    platform: str,
    item_id: Optional[str],
    item_url: Optional[str],
    item_name_norm: str,
    year: int,
    month_num: int,
    week: Optional[str],
) -> tuple[str, str, int, int, Optional[str], str]:
    if item_id:
        return platform, "item_id", year, month_num, week, item_id
    if item_url:
        return platform, "item_url", year, month_num, week, item_url
    return platform, "item_name", year, month_num, week, item_name_norm


def _preload_existing_history(db: Session, keys: set[tuple[str, str, int, int, Optional[str], str]]) -> dict[tuple[str, str, int, int, Optional[str], str], HistoricalMapping]:
    if not keys:
        return {}

    item_keys = {(platform, year, month_num, value) for platform, key_type, year, month_num, week, value in keys if key_type == "item_id"}
    url_keys = {(platform, year, month_num, value) for platform, key_type, year, month_num, week, value in keys if key_type == "item_url"}
    name_keys = {(platform, year, month_num, value) for platform, key_type, year, month_num, week, value in keys if key_type == "item_name"}

    existing = {}

    def add_rows(rows, key_type: str, value_attr: str):
        for row in rows:
            value = getattr(row, value_attr)
            key = (row.platform, key_type, row.year, row.month_num, row.week, value)
            existing[key] = row

    if item_keys:
        rows = db.query(HistoricalMapping).filter(
            tuple_(HistoricalMapping.platform, HistoricalMapping.year, HistoricalMapping.month_num, HistoricalMapping.item_id).in_(item_keys)
        ).all()
        add_rows(rows, "item_id", "item_id")
    if url_keys:
        rows = db.query(HistoricalMapping).filter(
            tuple_(HistoricalMapping.platform, HistoricalMapping.year, HistoricalMapping.month_num, HistoricalMapping.item_url).in_(url_keys)
        ).all()
        add_rows(rows, "item_url", "item_url")
    if name_keys:
        rows = db.query(HistoricalMapping).filter(
            tuple_(HistoricalMapping.platform, HistoricalMapping.year, HistoricalMapping.month_num, HistoricalMapping.item_name_norm).in_(name_keys)
        ).all()
        add_rows(rows, "item_name", "item_name_norm")
    return existing


def _json_safe_row(row: dict) -> dict:
    result = {}
    for key, value in row.items():
        cleaned = _clean_value(value)
        result[key] = cleaned
    return result


def _preload_models(db: Session, df: pd.DataFrame):
    model_code_values = {_clean_value(value) for value in df.get("型号码", [])}
    model_text_values = {_clean_value(value) for value in df.get("型号", [])}
    model_code_values.discard(None)
    model_text_values.discard(None)
    all_codes = model_code_values | model_text_values

    models_by_code = {}
    if all_codes:
        for model in db.query(ModelRecord).filter(ModelRecord.model_code.in_(all_codes)).all():
            models_by_code[model.model_code] = model

    models_by_name = {}
    if model_text_values:
        for model in db.query(ModelRecord).filter(ModelRecord.model_name.in_(model_text_values)).all():
            models_by_name.setdefault(model.model_name, []).append(model)

    return models_by_code, models_by_name


@router.post("/import")
def import_historical_mappings(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        xls = pd.ExcelFile(file.file)
        if not xls.sheet_names:
            raise HTTPException(400, "Excel 文件没有可读取的工作表")
        sheet_name = "rawdata" if "rawdata" in xls.sheet_names else xls.sheet_names[0]
        df = pd.read_excel(xls, sheet_name=sheet_name)
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(400, f"无法解析 Excel 文件: {e}")

    df.columns = [str(col).strip() for col in df.columns]
    if df.empty:
        df = pd.DataFrame([{col: None for col in df.columns}])
    import_batch = file.filename or f"import_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    success = 0
    created = 0
    updated = 0
    errors = []
    models_by_code, models_by_name = _preload_models(db, df)
    pending_rows = []
    history_keys = set()

    for idx, raw_row in df.iterrows():
        row = raw_row.to_dict()
        row_num = int(idx) + 2

        platform = _normalize_platform(_get(row, "商场")) or _normalize_platform(_get(row, "渠道"))
        item_name = _clean_value(_get(row, "标题"))
        model_text = _clean_value(_get(row, "型号"))
        year = _clean_int(_get(row, "年"))
        month_num = _clean_int(_get(row, "月"))

        missing = []
        if not platform:
            missing.append("商场/渠道不能为空")
        if not item_name:
            missing.append("标题不能为空")
        if year is None:
            missing.append("年不能为空")
        if month_num is None:
            missing.append("月不能为空")
        if missing:
            errors.append({"row": row_num, "reason": "；".join(missing)})
            continue
        if month_num < 1 or month_num > 12:
            errors.append({"row": row_num, "reason": "月必须为 1-12"})
            continue

        item_url = _clean_value(_get(row, "网址"))
        parsed = extract_item_id(item_url)
        item_id = None
        if parsed:
            parsed_platform, item_id = parsed
            platform = parsed_platform

        brand_code_raw = _clean_value(_get(row, "品牌码"))
        model_code_raw = _clean_value(_get(row, "型号码"))
        model, reason = _resolve_model(
            model_code_raw=model_code_raw,
            model_text=model_text,
            brand_code_raw=brand_code_raw,
            models_by_code=models_by_code,
            models_by_name=models_by_name,
        )
        if reason:
            errors.append({"row": row_num, "reason": reason})
            continue

        item_name_norm = _normalize_item_name(item_name)
        week = _clean_value(_get(row, "周"))
        month = f"{year:04d}-{month_num:02d}"
        match_key_type = _match_key_type(item_id, item_url, item_name_norm)
        history_key = _history_identity_key(
            platform=platform,
            item_id=item_id,
            item_url=item_url,
            item_name_norm=item_name_norm,
            year=year,
            month_num=month_num,
            week=week,
        )

        values = {
            "import_batch": import_batch,
            "platform": platform,
            "item_id": item_id,
            "item_url": item_url,
            "item_name": item_name,
            "item_name_norm": item_name_norm,
            "year": year,
            "month_num": month_num,
            "week": week,
            "month": month,
            "report_type": _clean_value(_get(row, "报告类型")),
            "channel": _clean_value(_get(row, "渠道")),
            "category_name_raw": _clean_value(_get(row, "品类")),
            "category_code_raw": _clean_value(_get(row, "品类码")),
            "brand_raw": _clean_value(_get(row, "品牌")),
            "brand_code_raw": brand_code_raw,
            "model_text": model_text,
            "model_code_raw": model_code_raw,
            "model_id": model.id if model else None,
            "model_code": model.model_code if model else None,
            "category_code": model.category_code if model else _clean_value(_get(row, "品类码")),
            "sales_amount": _clean_decimal(_get(row, "销额")),
            "sales_qty": _clean_int(_get(row, "销量")),
            "price": _clean_decimal(_get(row, "单价")),
            "match_key_type": match_key_type,
            "raw_payload": _json_safe_row(row),
            "updated_at": datetime.utcnow(),
        }

        pending_rows.append((history_key, values))
        history_keys.add(history_key)

    existing_by_key = _preload_existing_history(db, history_keys)
    for history_key, values in pending_rows:
        existing = existing_by_key.get(history_key)
        if existing:
            for key, value in values.items():
                setattr(existing, key, value)
            updated += 1
        else:
            new_row = HistoricalMapping(**values)
            db.add(new_row)
            existing_by_key[history_key] = new_row
            created += 1
        success += 1

    db.commit()
    return {"success": success, "created": created, "updated": updated, "errors": errors, "import_batch": import_batch}


@router.get("/batches")
def list_batches(db: Session = Depends(get_db)):
    rows = (
        db.query(
            HistoricalMapping.import_batch,
            func.count(HistoricalMapping.id).label("count"),
            func.max(HistoricalMapping.updated_at).label("updated_at"),
        )
        .filter(HistoricalMapping.import_batch.isnot(None))
        .group_by(HistoricalMapping.import_batch)
        .order_by(func.max(HistoricalMapping.updated_at).desc(), func.max(HistoricalMapping.id).desc())
        .all()
    )
    return [{"batch": r.import_batch, "count": r.count, "updated_at": r.updated_at} for r in rows]


@router.get("/mappings")
def list_mappings(
    platform: Optional[str] = Query(None),
    import_batch: Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    model_keyword: Optional[str] = Query(None),
    item_keyword: Optional[str] = Query(None),
    month: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = (
        db.query(HistoricalMapping, ModelRecord)
        .outerjoin(ModelRecord, HistoricalMapping.model_id == ModelRecord.id)
    )
    if platform:
        q = q.filter(HistoricalMapping.platform == platform.lower())
    if import_batch:
        q = q.filter(HistoricalMapping.import_batch == import_batch)
    if category_code:
        q = q.filter(HistoricalMapping.category_code == category_code)
    if month:
        q = q.filter(HistoricalMapping.month == month)
    if model_keyword:
        pattern = f"%{model_keyword}%"
        q = q.filter(or_(
            HistoricalMapping.model_text.ilike(pattern),
            HistoricalMapping.model_code.ilike(pattern),
            ModelRecord.model_name.ilike(pattern),
        ))
    if item_keyword:
        pattern = f"%{item_keyword}%"
        q = q.filter(or_(
            HistoricalMapping.item_name.ilike(pattern),
            HistoricalMapping.item_id.ilike(pattern),
            HistoricalMapping.item_url.ilike(pattern),
        ))

    total = q.count()
    rows = (
        q.order_by(HistoricalMapping.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id": hm.id,
            "platform": hm.platform,
            "item_id": hm.item_id,
            "item_url": hm.item_url,
            "item_name": hm.item_name,
            "brand_raw": hm.brand_raw,
            "brand_code_raw": hm.brand_code_raw,
            "model_text": hm.model_text,
            "model_id": hm.model_id,
            "model_code": hm.model_code,
            "standard_model_name": m.model_name if m else None,
            "category_code": hm.category_code,
            "category_name_raw": hm.category_name_raw,
            "year": hm.year,
            "month_num": hm.month_num,
            "month": hm.month,
            "week": hm.week,
            "sales_qty": hm.sales_qty,
            "price": float(hm.price) if hm.price is not None else None,
            "sales_amount": float(hm.sales_amount) if hm.sales_amount is not None else None,
            "import_batch": hm.import_batch,
            "match_key_type": hm.match_key_type,
            "updated_at": hm.updated_at,
        }
        for hm, m in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


@router.delete("/mappings/batch", status_code=204)
def delete_batch(body: BatchDeleteIn, db: Session = Depends(get_db)):
    deleted = (
        db.query(HistoricalMapping)
        .filter(HistoricalMapping.import_batch == body.import_batch)
        .delete(synchronize_session=False)
    )
    if deleted == 0:
        raise HTTPException(404, f"批次 '{body.import_batch}' 不存在或已删除")
    db.commit()


@router.delete("/mappings/{mapping_id}", status_code=204)
def delete_mapping(mapping_id: int, db: Session = Depends(get_db)):
    row = db.query(HistoricalMapping).filter(HistoricalMapping.id == mapping_id).first()
    if not row:
        raise HTTPException(404, "记录不存在")
    db.delete(row)
    db.commit()
