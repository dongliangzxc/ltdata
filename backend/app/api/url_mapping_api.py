# backend/app/api/url_mapping_api.py
"""URL→型号映射表 CRUD + Excel批量导入"""
from datetime import datetime
from typing import Optional
import io

from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import or_
from sqlalchemy.orm import Session
import openpyxl

from app.models.database import get_db
from app.models.schemas import (
    ItemUrlMapping, ItemUrlMappingIn, ItemUrlMappingOut,
    ModelRecord, PaginatedResponse,
)
from app.utils.url_utils import extract_item_id

router = APIRouter(prefix="/api/url-mappings", tags=["url-mappings"])

# 渠道名称 → platform 规范值
_PLATFORM_MAP = {
    "JD": "jd", "京东": "jd",
    "TMALL": "tmall", "天猫": "tmall",
    "TAOBAO": "taobao", "淘宝": "taobao",
    "SUNING": "suning", "苏宁": "suning",
}


def _to_out(m: ItemUrlMapping) -> ItemUrlMappingOut:
    model = m.model
    return ItemUrlMappingOut(
        id=m.id,
        platform=m.platform,
        item_id=m.item_id,
        item_url=m.item_url,
        model_id=m.model_id,
        price=float(m.price) if m.price is not None else None,
        brand_code=model.brand_code if model else None,
        model_code=model.model_code if model else None,
        brand_name=model.brand_name if model else None,
        model_name=model.model_name if model else None,
        created_at=m.created_at,
    )


@router.post("/import")
def import_url_mappings(file: UploadFile = File(...), db: Session = Depends(get_db)):
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
    model_lookup: dict[tuple[str, str], int] = {
        (m.brand_code.upper().strip(), m.model_code.upper().strip()): m.id
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

        model_id = model_lookup.get((brand_code, model_code))
        if not model_id:
            errors.append(f"第{row_idx}行：型号 [{brand_code}]{model_code} 不存在，已跳过")
            skipped += 1
            continue

        # Upsert
        existing = db.query(ItemUrlMapping).filter_by(
            platform=platform, item_id=item_id
        ).first()
        if existing:
            existing.model_id = model_id
            existing.price = price
            existing.item_url = url
            existing.updated_at = datetime.utcnow()
        else:
            db.add(ItemUrlMapping(
                platform=platform, item_id=item_id, item_url=url, model_id=model_id, price=price
            ))
        imported += 1

    db.commit()
    return {"imported": imported, "skipped": skipped, "errors": errors[:20]}


@router.get("", response_model=PaginatedResponse)
def list_url_mappings(
    keyword: Optional[str] = Query(None),
    platform: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(ItemUrlMapping)
    if platform:
        q = q.filter(ItemUrlMapping.platform == platform)
    if keyword:
        kw = f"%{keyword}%"
        q = q.outerjoin(ModelRecord, ItemUrlMapping.model_id == ModelRecord.id).filter(
            or_(
                ItemUrlMapping.item_id.ilike(kw),
                ModelRecord.model_code.ilike(kw),
                ModelRecord.brand_code.ilike(kw),
            )
        )
    total = q.count()
    rows = q.order_by(ItemUrlMapping.id.desc()).offset((page - 1) * page_size).limit(page_size).all()
    return PaginatedResponse(
        total=total, page=page, page_size=page_size,
        items=[_to_out(r) for r in rows],
    )


@router.post("", response_model=ItemUrlMappingOut)
def create_url_mapping(payload: ItemUrlMappingIn, db: Session = Depends(get_db)):
    if not db.query(ModelRecord).filter_by(id=payload.model_id).first():
        raise HTTPException(404, "型号不存在")
    existing = db.query(ItemUrlMapping).filter_by(
        platform=payload.platform, item_id=payload.item_id
    ).first()
    if existing:
        raise HTTPException(409, "该 platform+item_id 已存在，请使用编辑功能")
    m = ItemUrlMapping(
        platform=payload.platform,
        item_id=payload.item_id,
        item_url=payload.item_url,
        model_id=payload.model_id,
        price=payload.price,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.put("/{mapping_id}", response_model=ItemUrlMappingOut)
def update_url_mapping(mapping_id: int, payload: ItemUrlMappingIn, db: Session = Depends(get_db)):
    m = db.query(ItemUrlMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(404, "映射记录不存在")
    if not db.query(ModelRecord).filter_by(id=payload.model_id).first():
        raise HTTPException(404, "型号不存在")
    m.platform = payload.platform
    m.item_id = payload.item_id
    m.item_url = payload.item_url
    m.model_id = payload.model_id
    m.price = payload.price
    m.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(m)
    return _to_out(m)


@router.delete("/{mapping_id}")
def delete_url_mapping(mapping_id: int, db: Session = Depends(get_db)):
    m = db.query(ItemUrlMapping).filter_by(id=mapping_id).first()
    if not m:
        raise HTTPException(404, "映射记录不存在")
    db.delete(m)
    db.commit()
    return {"deleted": True}
