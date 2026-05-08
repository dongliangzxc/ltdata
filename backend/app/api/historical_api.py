"""历史库管理 API
- POST   /api/historical/import           Excel 导入历史对照表（upsert）
- GET    /api/historical/batches          查询所有批次名称列表
- GET    /api/historical/mappings         分页查询映射（platform / import_batch 筛选）
- DELETE /api/historical/mappings/batch   按批次批量删除（静态路由，必须在 /{id} 之前）
- DELETE /api/historical/mappings/{id}    删除单条映射
"""
from datetime import datetime
from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.database import get_db
from app.models.schemas import HistoricalMapping, ModelRecord

router = APIRouter(prefix="/api/historical", tags=["historical"])


class BatchDeleteIn(BaseModel):
    import_batch: str


# ── 导入 ──────────────────────────────────────────────────────────────────────

@router.post("/import")
def import_historical_mappings(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    try:
        df = pd.read_excel(file.file)
    except Exception as e:
        raise HTTPException(400, f"无法解析 Excel 文件: {e}")

    required_cols = {"platform", "item_id", "model_code"}
    missing = required_cols - set(df.columns)
    if missing:
        raise HTTPException(400, f"Excel 缺少必需列: {', '.join(sorted(missing))}")

    import_batch = file.filename or f"import_{datetime.utcnow().strftime('%Y%m%d%H%M%S')}"

    # 预加载 model_code → model_id，避免 N+1
    raw_codes = [str(r).strip() for r in df["model_code"] if pd.notna(r) and str(r).strip()]
    model_map: dict[str, int] = {
        m.model_code: m.id
        for m in db.query(ModelRecord).filter(ModelRecord.model_code.in_(raw_codes)).all()
    }

    success, errors = 0, []

    for idx, row in df.iterrows():
        platform   = str(row.get("platform",   "")).strip().lower()
        item_id    = str(row.get("item_id",    "")).strip()
        model_code = str(row.get("model_code", "")).strip()

        if not platform or not item_id or not model_code:
            errors.append({"row": int(idx) + 2, "reason": "platform / item_id / model_code 不能为空"})
            continue

        model_id = model_map.get(model_code)
        if model_id is None:
            errors.append({"row": int(idx) + 2, "reason": f"model_code '{model_code}' 在型号库中不存在"})
            continue

        existing = db.query(HistoricalMapping).filter_by(
            platform=platform, item_id=item_id
        ).first()
        if existing:
            existing.model_id     = model_id
            existing.import_batch = import_batch
            existing.updated_at   = datetime.utcnow()
        else:
            db.add(HistoricalMapping(
                platform=platform,
                item_id=item_id,
                model_id=model_id,
                import_batch=import_batch,
            ))
        success += 1

    db.commit()
    return {"success": success, "errors": errors, "import_batch": import_batch}


# ── 批次列表 ──────────────────────────────────────────────────────────────────

@router.get("/batches")
def list_batches(db: Session = Depends(get_db)):
    rows = (
        db.query(HistoricalMapping.import_batch, func.count(HistoricalMapping.id).label("count"))
        .filter(HistoricalMapping.import_batch.isnot(None))
        .group_by(HistoricalMapping.import_batch)
        .all()
    )
    return [{"batch": r.import_batch, "count": r.count} for r in rows]


# ── 映射查询 ──────────────────────────────────────────────────────────────────

@router.get("/mappings")
def list_mappings(
    platform:     Optional[str] = Query(None),
    import_batch: Optional[str] = Query(None),
    page:         int = Query(1, ge=1),
    page_size:    int = Query(20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = (
        db.query(HistoricalMapping, ModelRecord)
        .join(ModelRecord, HistoricalMapping.model_id == ModelRecord.id)
    )
    if platform:
        q = q.filter(HistoricalMapping.platform == platform.lower())
    if import_batch:
        q = q.filter(HistoricalMapping.import_batch == import_batch)

    total = q.count()
    rows = (
        q.order_by(HistoricalMapping.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
        .all()
    )

    items = [
        {
            "id":           hm.id,
            "platform":     hm.platform,
            "item_id":      hm.item_id,
            "model_id":     hm.model_id,
            "model_code":   m.model_code,
            "brand_code":   m.brand_code,
            "import_batch": hm.import_batch,
            "updated_at":   hm.updated_at,
        }
        for hm, m in rows
    ]
    return {"total": total, "page": page, "page_size": page_size, "items": items}


# ── 删除（静态路由 /batch 必须在动态路由 /{id} 之前注册）────────────────────

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
