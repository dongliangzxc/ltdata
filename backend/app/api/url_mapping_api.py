# backend/app/api/url_mapping_api.py
"""URL→型号映射表 CRUD + Excel批量导入"""
from datetime import datetime
from typing import Optional
import io
import os
from pathlib import Path

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from fastapi.responses import Response
from pydantic import BaseModel
from urllib.parse import quote
from sqlalchemy import and_, or_
from sqlalchemy.orm import Session, joinedload
import openpyxl

from app.core.auth_deps import get_current_user
from app.core.permissions import visible_category_codes
from app.models.database import get_db
from app.models.schemas import (
    ItemUrlMapping, ItemUrlMappingIn, ItemUrlMappingOut,
    ModelRecord, BrandRecord, BrandCategory, CategoryExtraField,
    PaginatedResponse, Category, User,
)
from app.utils.url_utils import extract_item_id
from app.services.import_helper import save_tmp_file, read_columns, find_best_template, col_fingerprint

router = APIRouter(prefix="/api/url-mappings", tags=["url-mappings"])

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./uploads")

# 渠道名称 → platform 规范值
_PLATFORM_MAP = {
    "JD": "jd", "京东": "jd",
    "TMALL": "tmall", "天猫": "tmall", "TM": "tmall", "天猫全部": "tmall",
    "TAOBAO": "taobao", "淘宝": "taobao", "TB": "taobao",
    "SUNING": "suning", "苏宁": "suning",
    "DOUYIN": "douyin", "抖音": "douyin", "DY": "douyin",
    "AMAZON": "amazon", "亚马逊": "amazon", "AMZ": "amazon",
    "SHOPEE": "shopee", "虾皮": "shopee", "西皮": "shopee",
}

_LEGACY_HEADPHONE_PLATFORMS = {"jd", "tmall", "taobao"}


def _clean_cell(value) -> str:
    """把 Excel 单元格读为去空白字符串；空值/NaN/None 归一为 ''（避免出现 'nan'）。"""
    if value is None:
        return ""
    try:
        if pd.isna(value):
            return ""
    except (TypeError, ValueError):
        pass
    return str(value).strip()


def _visible_url_mapping_category_codes(db: Session, current_user: User) -> set[str] | None:
    all_codes = [code for code, in db.query(Category.code).order_by(Category.sort_order, Category.name).all()]
    if not all_codes:
        return None
    return set(visible_category_codes(current_user, all_codes))


def _ensure_url_mapping_category_visible(db: Session, current_user: User, selected_category_code: str | None) -> None:
    """按导入时选择的品类校验权限（不按型号归属品类拦截）。

    用户选择了自己有权限的品类即可导入；型号归属品类仅作参考，
    避免一个品牌跨多个品类时（如 360 门锁/摄像头）被型号品类拦截。
    """
    if not selected_category_code:
        return
    visible_codes = _visible_url_mapping_category_codes(db, current_user)
    if visible_codes is not None and selected_category_code not in visible_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


def _ensure_url_mapping_model_visible(db: Session, current_user: User, model: ModelRecord | None) -> None:
    """手动新增/编辑/删除单条映射时，校验型号归属品类在用户可见范围内。"""
    if not model or not model.category_code:
        return
    visible_codes = _visible_url_mapping_category_codes(db, current_user)
    if visible_codes is not None and model.category_code not in visible_codes:
        raise HTTPException(status_code=403, detail="无权限访问该品类")


def _category_has_series(db: Session, category_code: str | None) -> bool:
    """该品类是否配置了「产品系列」扩展字段（系列品类：品牌+系列+型号码 定位型号）。"""
    if not category_code:
        return False
    return db.query(CategoryExtraField).filter(
        CategoryExtraField.category_code == category_code,
        CategoryExtraField.field_key == "series",
    ).first() is not None


def _get_or_create_url_import_model(
    db: Session,
    *,
    brand_code: str,
    model_code: str,
    category_code: str | None,
    series: str | None = None,
) -> ModelRecord | None:
    """型号匹配不到时自动创建型号记录（复用品牌主数据，品牌自动挂到所选品类）。

    返回创建的型号；品牌为空/占位或缺少所选品类时返回 None（无法创建）。
    """
    if _is_unusable_brand_code(brand_code):
        return None
    if not category_code or not model_code or model_code in ("-", "—", "--", "未知"):
        return None
    # 品牌主数据不存在时补建（品牌码即品牌名兜底）
    brand = db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first()
    if not brand:
        db.add(BrandRecord(brand_code=brand_code, brand_name=brand_code))
        db.flush()

    # 品牌挂到所选品类（品牌可归属多品类）
    if not db.query(BrandCategory).filter_by(brand_code=brand_code, category_code=category_code).first():
        db.add(BrandCategory(brand_code=brand_code, category_code=category_code))

    existing_query = db.query(ModelRecord).filter(
        ModelRecord.brand_code == brand_code,
        ModelRecord.model_code == model_code,
        ModelRecord.category_code == category_code,
    )
    if series is not None:
        existing_query = existing_query.filter(ModelRecord.series == series)
    existing = existing_query.first()
    if existing:
        return existing

    model = ModelRecord(
        brand_code=brand_code,
        model_code=model_code,
        category_code=category_code,
        series=series,
        brand_name=brand.brand_name if brand else brand_code,
        status="active",
    )
    db.add(model)
    db.flush()
    return model


_SERIES_MODEL_CODE_PLACEHOLDERS = ("", "—", "--", "未知")


def _series_model_code(model_code: str) -> str:
    """系列品类里型号码允许为占位（如 vrar 的 '-'），空/其它占位统一存 '-'。"""
    return model_code if model_code not in _SERIES_MODEL_CODE_PLACEHOLDERS else "-"


def _resolve_series_model(
    db: Session,
    *,
    brand_code: str,
    model_code: str,
    category_code: str | None,
    series: str,
) -> ModelRecord | None:
    """系列品类定位型号：品牌 + 产品系列（型号码可为占位 '-'）。

    按精确度依次尝试：品类+型号码+系列 → 品类+系列 → 型号码+系列 → 系列。
    """
    code = _series_model_code(model_code)
    attempts = [
        [ModelRecord.brand_code == brand_code, ModelRecord.series == series,
         ModelRecord.model_code == code, ModelRecord.category_code == category_code] if category_code else None,
        [ModelRecord.brand_code == brand_code, ModelRecord.series == series,
         ModelRecord.category_code == category_code] if category_code else None,
        [ModelRecord.brand_code == brand_code, ModelRecord.series == series, ModelRecord.model_code == code],
        [ModelRecord.brand_code == brand_code, ModelRecord.series == series],
    ]
    for filters in attempts:
        if not filters:
            continue
        model = db.query(ModelRecord).filter(*filters).first()
        if model:
            return model
    return None


def _get_or_create_series_url_import_model(
    db: Session,
    *,
    brand_code: str,
    model_code: str,
    category_code: str | None,
    series: str,
) -> ModelRecord | None:
    """系列品类型号匹配不到时自动创建（保留占位型号码 + 产品系列）。"""
    if _is_unusable_brand_code(brand_code) or not category_code or not series:
        return None
    code = _series_model_code(model_code)
    brand = db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first()
    if not brand:
        db.add(BrandRecord(brand_code=brand_code, brand_name=brand_code))
        db.flush()
    if not db.query(BrandCategory).filter_by(brand_code=brand_code, category_code=category_code).first():
        db.add(BrandCategory(brand_code=brand_code, category_code=category_code))
    existing = db.query(ModelRecord).filter(
        ModelRecord.brand_code == brand_code,
        ModelRecord.model_code == code,
        ModelRecord.category_code == category_code,
        ModelRecord.series == series,
    ).first()
    if existing:
        return existing
    model = ModelRecord(
        brand_code=brand_code,
        model_code=code,
        category_code=category_code,
        series=series,
        brand_name=brand.brand_name if brand else brand_code,
        status="active",
    )
    db.add(model)
    db.flush()
    return model


def _is_unusable_brand_code(value: str | None) -> bool:
    text = (value or "").strip()
    if not text:
        return True
    return text.upper() in {"-", "—", "--", "UNKNOWN", "未知"}


def _legacy_headphone_category(m: ItemUrlMapping) -> tuple[str | None, str | None]:
    platform = (m.platform or "").strip().lower()
    if m.model_id is None and m.brand_code and m.source is None and platform in _LEGACY_HEADPHONE_PLATFORMS:
        return "headphone", "耳机"
    return None, None


def _to_out(m: ItemUrlMapping, category: Category | None = None) -> ItemUrlMappingOut:
    model = m.model
    model_category = getattr(model, "category", None) if model else None
    fallback_category_code, fallback_category_name = _legacy_headphone_category(m)
    category_code = m.category_code or (model.category_code if model else None) or fallback_category_code
    if category is None:
        category = model_category if (model_category and model_category.code == category_code) else None
    return ItemUrlMappingOut(
        id=m.id,
        platform=m.platform,
        item_id=m.item_id,
        item_url=m.item_url,
        model_id=m.model_id,
        price=float(m.price) if m.price is not None else None,
        brand_code=model.brand_code if model else m.brand_code,
        model_code=model.model_code if model else None,
        brand_name=model.brand_name if model else None,
        model_name=model.model_name if model else None,
        series=model.series if model else None,
        category_code=category_code,
        category_name=category.name if category else None,
        item_name=None,
        source=m.source,
        data_year=m.data_year,
        data_month=m.data_month,
        operator=None,
        created_at=m.created_at,
        updated_at=m.updated_at,
    )


class UrlMappingConfirmPayload(BaseModel):
    temp_file_id: str
    mapping: dict
    ignore_columns: list = []
    category_code: str
    save_template_name: Optional[str] = None
    data_year: Optional[int] = None
    data_month: Optional[int] = None


class UrlMappingBulkDeletePayload(BaseModel):
    category_code: str


@router.get("/template")
def download_url_mapping_template():
    from openpyxl import Workbook

    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "URL映射"
    sheet.append(["platform", "item_url", "brand_code", "model_code", "series", "price"])
    sheet.append(["jd", "https://item.jd.com/100123456.html", "SONY", "X95L", "", 1299.9])
    output = io.BytesIO()
    workbook.save(output)
    quoted_filename = quote("URL映射导入模板.xlsx")
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"}
    return Response(
        content=output.getvalue(),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers=headers,
    )


@router.post("/headers")
async def url_mapping_headers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """P10: Step 1 — read columns, suggest mapping template."""
    temp_file_id, save_path, filename = await save_tmp_file(file, UPLOAD_DIR)
    columns = read_columns(save_path)
    best_tmpl, score = find_best_template(columns, "url", db)
    return {
        "temp_file_id": temp_file_id,
        "filename": filename,
        "columns": columns,
        "suggested_template": {
            "id": best_tmpl.id,
            "name": best_tmpl.name,
            "mapping": best_tmpl.mapping,
            "ignore_columns": best_tmpl.ignore_columns or [],
        } if best_tmpl else None,
        "match_score": score,
    }


@router.post("/confirm")
def url_mapping_confirm(
    payload: UrlMappingConfirmPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """P10: Step 2 — parse file with mapping, upsert item_url_mappings."""
    from app.models.schemas import ItemUrlMapping, ModelRecord as ModelORM

    _ensure_url_mapping_category_visible(db, current_user, payload.category_code)

    tmp_dir = Path(UPLOAD_DIR) / "tmp"
    candidates = list(tmp_dir.glob(f"*{payload.temp_file_id}*")) if tmp_dir.exists() else []
    if not candidates:
        direct = tmp_dir / payload.temp_file_id
        if direct.exists():
            candidates = [direct]
    if not candidates:
        raise HTTPException(status_code=404, detail="Temp file not found or expired")
    file_path = candidates[0]

    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(file_path, dtype=str, encoding="gbk")
    else:
        df = pd.read_excel(file_path, sheet_name=0, dtype=str)
    df.columns = [str(c).strip() for c in df.columns]

    ignore_set = set(payload.ignore_columns)
    rename_map = {
        col: target
        for col, target in payload.mapping.items()
        if col in df.columns and col not in ignore_set
    }
    df = df.rename(columns=rename_map)

    inserted = 0
    updated = 0
    skipped = 0
    errors = []
    warnings = []
    payload_fields = getattr(payload, "model_fields_set", getattr(payload, "__fields_set__", set()))
    seen_keys: dict[tuple[str, str], ItemUrlMapping] = {}

    for i, row in enumerate(df.itertuples(index=False), start=2):
        row_dict = row._asdict()

        platform_raw = _clean_cell(row_dict.get("platform"))
        item_url = _clean_cell(row_dict.get("item_url"))
        brand_code = _clean_cell(row_dict.get("brand_code"))
        model_code = _clean_cell(row_dict.get("model_code"))
        series_value = _clean_cell(row_dict.get("series")) or None

        if not platform_raw or not item_url or not brand_code:
            errors.append(f"Row {i}: missing required field")
            continue

        # Normalize platform: try map lookup (handles Chinese/uppercase), fallback to lowercase
        platform = _PLATFORM_MAP.get(platform_raw.upper(), platform_raw.lower())

        # Extract item_id from URL
        url_info = extract_item_id(item_url)
        if not url_info:
            errors.append(f"Row {i}: cannot extract item_id from URL '{item_url}'")
            continue
        url_platform, item_id = url_info

        # Lookup model — 系列品类按「品牌+产品系列」定位（型号码允许占位，如 vrar 的 '-'）；其余品类按品牌+型号码
        is_series_category = _category_has_series(db, payload.category_code)

        model = None
        if is_series_category and series_value:
            model = _resolve_series_model(
                db, brand_code=brand_code, model_code=model_code,
                category_code=payload.category_code, series=series_value,
            )
            if not model:
                model = _get_or_create_series_url_import_model(
                    db, brand_code=brand_code, model_code=model_code,
                    category_code=payload.category_code, series=series_value,
                )
                if model is None:
                    errors.append(f"Row {i}: model ({brand_code}, {series_value}) not found")
                    continue
            if model.category_code and payload.category_code and model.category_code != payload.category_code:
                warnings.append(
                    f"Row {i}: 型号归属品类（{model.category_code}）与所选品类（{payload.category_code}）不一致，已按型号原品类挂接"
                )
        elif model_code not in ("", "-", "—", "--", "未知"):
            if payload.category_code:
                model = (
                    db.query(ModelORM)
                    .filter(
                        ModelORM.brand_code == brand_code,
                        ModelORM.model_code == model_code,
                        ModelORM.category_code == payload.category_code,
                    )
                    .first()
                )
            if not model:
                model = (
                    db.query(ModelORM)
                    .filter(ModelORM.brand_code == brand_code, ModelORM.model_code == model_code)
                    .first()
                )
            if not model:
                model = _get_or_create_url_import_model(
                    db, brand_code=brand_code, model_code=model_code,
                    category_code=payload.category_code,
                )
                if model is None:
                    errors.append(f"Row {i}: model ({brand_code}, {model_code}) not found")
                    continue
            # Category mismatch warning (non-blocking)
            if model.category_code and payload.category_code and model.category_code != payload.category_code:
                warnings.append(
                    f"Row {i}: 型号归属品类（{model.category_code}）与所选品类（{payload.category_code}）不一致，已按型号原品类挂接"
                )
        else:
            model = None

        price_raw = row_dict.get("price")
        try:
            price = float(str(price_raw).strip()) if price_raw and str(price_raw).strip() not in ("", "nan", "None") else None
        except (ValueError, TypeError):
            price = None

        key = (url_platform, item_id)
        existing = seen_keys.get(key)
        if existing is None:
            existing = (
                db.query(ItemUrlMapping)
                .filter(ItemUrlMapping.platform == url_platform, ItemUrlMapping.item_id == item_id)
                .first()
            )
        if existing:
            existing.model_id = model.id if model else None
            existing.brand_code = brand_code
            if payload.category_code:
                existing.category_code = payload.category_code
            if price is not None:
                existing.price = price
            existing.source = 'url_import'
            if "data_year" in payload_fields:
                existing.data_year = payload.data_year
            if "data_month" in payload_fields:
                existing.data_month = payload.data_month
            seen_keys[key] = existing
            updated += 1
        else:
            new_mapping = ItemUrlMapping(
                platform=url_platform,
                item_id=item_id,
                item_url=item_url,
                brand_code=brand_code,
                category_code=payload.category_code,
                model_id=model.id if model else None,
                price=price,
                source='url_import',
                data_year=payload.data_year,
                data_month=payload.data_month,
            )
            db.add(new_mapping)
            seen_keys[key] = new_mapping
            inserted += 1

    if inserted > 0 or updated > 0:
        db.commit()

    if payload.save_template_name and (inserted + updated) > 0:
        from app.models.schemas import ColumnTemplate
        tmpl = ColumnTemplate(
            name=payload.save_template_name,
            module="url",
            mapping=payload.mapping,
            ignore_columns=payload.ignore_columns,
            col_fingerprint=col_fingerprint(list(payload.mapping.keys())),
        )
        db.add(tmpl)
        try:
            db.commit()
        except Exception:
            db.rollback()

    return {"inserted": inserted, "updated": updated, "skipped": skipped, "errors": errors, "warnings": warnings[:20]}


@router.post("/import")
def import_url_mappings(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    从 Excel rawdata sheet 批量导入 URL→型号 映射。
    期望列：渠道 / 网址 / 品牌码 / 型号码 / 单价
    采用 upsert（platform+item_id 冲突时更新 model_id 和 price）。
    """
    contents = file.file.read()
    wb = openpyxl.load_workbook(io.BytesIO(contents), read_only=True, data_only=True)

    # 优先找名为 rawdata 的 sheet，否则取第一个
    sheet = wb["rawdata"] if "rawdata" in wb.sheetnames else wb.active

    rows = list(sheet.iter_rows(values_only=True))
    if not rows:
        return {"imported": 0, "skipped": 0, "errors": []}

    # 构建列名→列索引映射（第一行为表头）
    header = [str(c).strip() if c is not None else "" for c in rows[0]]
    col = {name: idx for idx, name in enumerate(header)}

    # 必需列：品牌码/型号码 可以用 品牌/型号 替代（rawdata sheet 有时只有后者）
    required = {"渠道", "网址"}
    required_brand = {"品牌码", "品牌"}   # 至少有其中一列
    required_model = {"型号码", "型号"}   # 至少有其中一列
    missing = required - set(col.keys())
    if missing:
        raise HTTPException(400, detail=f"Excel 缺少必需列：{missing}")
    if not (required_brand & set(col.keys())):
        raise HTTPException(400, detail="Excel 缺少品牌列（需要「品牌码」或「品牌」）")
    if not (required_model & set(col.keys())):
        raise HTTPException(400, detail="Excel 缺少型号列（需要「型号码」或「型号」）")

    # 构建 (brand_code, model_code) → model_id 缓存
    all_models = db.query(ModelRecord).all()
    model_lookup: dict[tuple[str, str], ModelRecord] = {
        (m.brand_code.upper().strip(), m.model_code.upper().strip()): m
        for m in all_models
    }

    imported = 0
    skipped = 0
    errors: list[str] = []
    seen_keys: set[tuple[str, str]] = set()  # 同一文件内去重，避免重复 INSERT

    for row_idx, row in enumerate(rows[1:], start=2):
        try:
            platform_raw = str(row[col["渠道"]] or "").strip().upper()
            platform = _PLATFORM_MAP.get(platform_raw)
            url = str(row[col["网址"]] or "").strip()
            brand_code_raw = row[col["品牌码"]] if "品牌码" in col else None
            if not brand_code_raw and "品牌" in col:
                brand_code_raw = row[col["品牌"]]
            brand_code = str(brand_code_raw or "").strip().upper()

            model_code_raw = row[col["型号码"]] if "型号码" in col else None
            if not model_code_raw and "型号" in col:
                model_code_raw = row[col["型号"]]
            model_code = str(model_code_raw or "").strip().upper()
            price_raw = row[col["单价"]] if "单价" in col else None
            price = float(price_raw) if price_raw not in (None, "") else None
        except Exception as e:
            errors.append(f"第{row_idx}行解析错误：{e}")
            skipped += 1
            continue

        if not platform or not url or not brand_code or not model_code:
            skipped += 1
            continue

        url_info = extract_item_id(url)
        if not url_info or url_info[0] != platform:
            skipped += 1
            continue

        _, item_id = url_info
        key = (platform, item_id)

        # 同文件内重复行：只保留最后一条（继续处理，覆盖 seen_keys）
        if key in seen_keys:
            skipped += 1
            continue
        seen_keys.add(key)

        model = model_lookup.get((brand_code, model_code))
        if not model:
            errors.append(f"第{row_idx}行：型号 [{brand_code}]{model_code} 不存在，已跳过")
            skipped += 1
            continue
        _ensure_url_mapping_model_visible(db, current_user, model)
        model_id = model.id

        # Upsert
        existing = db.query(ItemUrlMapping).filter_by(
            platform=platform, item_id=item_id
        ).first()
        if existing:
            existing.model_id = model_id
            existing.price = price
            existing.item_url = url
            existing.updated_at = datetime.utcnow()
            existing.source = 'url_import'
        else:
            db.add(ItemUrlMapping(
                platform=platform, item_id=item_id, item_url=url, model_id=model_id, price=price,
                source='url_import',
            ))
        imported += 1

    db.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}


@router.get("", response_model=PaginatedResponse)
def list_url_mappings(
    keyword: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    year: Optional[int] = Query(None),
    month: Optional[int] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    visible_codes = _visible_url_mapping_category_codes(db, current_user)
    q = db.query(ItemUrlMapping).outerjoin(ModelRecord, ItemUrlMapping.model_id == ModelRecord.id).filter(
        or_(ItemUrlMapping.brand_code.isnot(None), ItemUrlMapping.model_id.isnot(None))
    )
    legacy_headphone_filter = and_(
        ItemUrlMapping.model_id.is_(None),
        ItemUrlMapping.brand_code.isnot(None),
        ItemUrlMapping.source.is_(None),
        ItemUrlMapping.platform.in_(_LEGACY_HEADPHONE_PLATFORMS),
    )
    if visible_codes is not None:
        q = q.filter(or_(
            ModelRecord.category_code.in_(visible_codes),
            ItemUrlMapping.category_code.in_(visible_codes),
            and_(ItemUrlMapping.model_id.is_(None), ItemUrlMapping.category_code.is_(None), ~legacy_headphone_filter),
            and_(legacy_headphone_filter, "headphone" in visible_codes),
        ))
    if platform:
        q = q.filter(ItemUrlMapping.platform == platform)
    if year is not None:
        q = q.filter(ItemUrlMapping.data_year == year)
    if month is not None:
        q = q.filter(ItemUrlMapping.data_month == month)
    if keyword:
        kw = f"%{keyword}%"
        q = q.filter(
            or_(
                ItemUrlMapping.item_id.ilike(kw),
                ModelRecord.model_code.ilike(kw),
                ModelRecord.brand_code.ilike(kw),
            )
        )
    # 品类筛选要与列表展示的品类口径一致：展示优先取记录品类
    # （`ItemUrlMapping.category_code`，占位/导入时记录），为空再回退型号品类。
    # 若这里仍用「型号品类 OR 记录品类」，会导致型号在 A 品类、记录在 B 品类的行
    # 出现在 A 品类筛选下却显示为 B 品类（例如 移动电源 记录挂到 door_lock 型号）。
    if category_code:
        mapping_category_match = and_(
            ItemUrlMapping.category_code.isnot(None),
            ItemUrlMapping.category_code == category_code,
        )
        model_category_match = and_(
            ItemUrlMapping.category_code.is_(None),
            ModelRecord.category_code == category_code,
        )
        if category_code == "headphone":
            # 无型号、无记录品类的历史耳机映射，展示口径回退为 headphone
            q = q.filter(or_(
                mapping_category_match,
                model_category_match,
                legacy_headphone_filter,
            ))
        else:
            q = q.filter(or_(mapping_category_match, model_category_match))
    total = q.count()
    rows = (
        q.options(joinedload(ItemUrlMapping.model).joinedload(ModelRecord.category))
        .order_by(ItemUrlMapping.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )
    record_category_codes = {m.category_code for m in rows if m.category_code}
    category_by_code = {
        c.code: c
        for c in db.query(Category).filter(Category.code.in_(record_category_codes)).all()
    } if record_category_codes else {}
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[_to_out(r, category_by_code.get(r.category_code)) for r in rows],
    )


@router.post("", response_model=ItemUrlMappingOut)
def create_url_mapping(
    payload: ItemUrlMappingIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    model_for_brand = db.query(ModelRecord).filter_by(id=payload.model_id).first() if payload.model_id else None
    if not model_for_brand:
        raise HTTPException(404, "型号不存在")
    _ensure_url_mapping_model_visible(db, current_user, model_for_brand)
    existing = db.query(ItemUrlMapping).filter_by(
        platform=payload.platform, item_id=payload.item_id
    ).first()
    if existing:
        raise HTTPException(409, "该 platform+item_id 已存在，请使用编辑功能")
    m = ItemUrlMapping(
        platform=payload.platform,
        item_id=payload.item_id,
        item_url=payload.item_url,
        brand_code=model_for_brand.brand_code if model_for_brand else payload.brand_code,
        model_id=payload.model_id,
        category_code=payload.category_code or (model_for_brand.category_code if model_for_brand else None),
        price=payload.price,
        source='manual',
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.put("/{mapping_id}", response_model=ItemUrlMappingOut)
def update_url_mapping(
    mapping_id: int,
    payload: ItemUrlMappingIn,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = db.query(ItemUrlMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(404, "映射记录不存在")
    existing_model = db.query(ModelRecord).filter_by(id=m.model_id).first() if m.model_id else None
    _ensure_url_mapping_model_visible(db, current_user, existing_model)
    model_for_brand = db.query(ModelRecord).filter_by(id=payload.model_id).first() if payload.model_id else None
    if not model_for_brand:
        raise HTTPException(404, "型号不存在")
    _ensure_url_mapping_model_visible(db, current_user, model_for_brand)
    m.platform = payload.platform
    m.item_id = payload.item_id
    m.item_url = payload.item_url
    m.brand_code = model_for_brand.brand_code if model_for_brand else payload.brand_code
    m.model_id = payload.model_id
    m.category_code = payload.category_code or (model_for_brand.category_code if model_for_brand else None)
    m.price = payload.price
    m.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.delete("/{mapping_id}")
def delete_url_mapping(
    mapping_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    m = db.query(ItemUrlMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(404, "映射记录不存在")
    existing_model = db.query(ModelRecord).filter_by(id=m.model_id).first() if m.model_id else None
    _ensure_url_mapping_model_visible(db, current_user, existing_model)
    db.delete(m)
    db.commit()
    return {"deleted": True}


def _url_mapping_category_match_query(db: Session, category_code: str):
    """与列表页品类筛选口径一致：记录品类或型号归属品类命中即算该品类。"""
    return (
        db.query(ItemUrlMapping.id)
        .outerjoin(ModelRecord, ItemUrlMapping.model_id == ModelRecord.id)
        .filter(or_(
            ModelRecord.category_code == category_code,
            ItemUrlMapping.category_code == category_code,
        ))
    )


@router.get("/category-count")
def url_mapping_category_count(
    category_code: str = Query(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _ensure_url_mapping_category_visible(db, current_user, category_code)
    count = _url_mapping_category_match_query(db, category_code).count()
    return {"category_code": category_code, "count": count}


@router.post("/bulk-delete")
def bulk_delete_url_mappings(
    payload: UrlMappingBulkDeletePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """按品类批量删除 URL 映射，删除范围与列表页品类筛选一致。"""
    _ensure_url_mapping_category_visible(db, current_user, payload.category_code)
    ids = [row[0] for row in _url_mapping_category_match_query(db, payload.category_code).all()]
    deleted = 0
    chunk_size = 1000
    for start in range(0, len(ids), chunk_size):
        chunk = ids[start:start + chunk_size]
        deleted += (
            db.query(ItemUrlMapping)
            .filter(ItemUrlMapping.id.in_(chunk))
            .delete(synchronize_session=False)
        )
    db.commit()
    return {"category_code": payload.category_code, "deleted": deleted}
