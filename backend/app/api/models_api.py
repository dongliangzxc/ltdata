"""
型号管理 API
支持 Excel 导入（型号 + 型号规格两个 sheet）、分页查询、增删改查
唯一键：brand_code + model_code
"""
import io
import math
import pandas as pd
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from sqlalchemy.orm import Session
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy import func
from app.models.database import get_db
from app.models.schemas import (
    ModelRecord, ModelSpec, ModelAlias,
    ModelIn, ModelOut, ModelSpecOut, ModelAliasOut,
    PaginatedResponse,
)

router = APIRouter(prefix="/api/models", tags=["models"])


def _clean_val(v):
    if v is None:
        return None
    try:
        if isinstance(v, float) and math.isnan(v):
            return None
    except (TypeError, ValueError):
        pass
    try:
        if pd.isna(v):
            return None
    except (TypeError, ValueError):
        pass
    return v


def _to_int(v):
    try:
        return int(float(v)) if v is not None else None
    except (ValueError, TypeError):
        return None


def _to_float(v):
    try:
        return float(v) if v is not None else None
    except (ValueError, TypeError):
        return None


def _parse_models_file(content: bytes) -> dict:
    """
    解析 Excel，返回解析结果（不操作数据库）。
    返回:
      total_rows: 读取到的行数
      valid_rows: 有效行数（brand_code + model_code 非空）
      preview:    前 10 行预览数据
      errors:     [{row, message}] 格式错误列表
      warnings:   [{row, message}] 格式警告列表
    """
    try:
        df_model = pd.read_excel(io.BytesIO(content), sheet_name="型号", dtype=str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"读取「型号」sheet 失败：{e}")

    try:
        df_spec = pd.read_excel(io.BytesIO(content), sheet_name="型号规格", dtype=str)
    except Exception:
        df_spec = pd.DataFrame()

    df_model.columns = [str(c).strip() for c in df_model.columns]
    df_model = df_model.dropna(axis=1, how="all")

    def _apply_col_map(df):
        priority = {"品牌码": "brand_code", "型号码": "model_code"}
        fallback = {"品牌":   "brand_code", "型号":   "model_code"}
        other    = {
            "品类": "category_name", "品牌名称": "brand_name", "型号名称": "model_name",
            "上市年": "launch_year", "上市月": "launch_month", "上市周": "launch_week",
            "上市价格": "launch_price", "网址": "url",
            "规格名称": "spec_name", "规格值": "spec_value",
        }
        rename = {}
        for src, dst in priority.items():
            if src in df.columns:
                rename[src] = dst
        for src, dst in fallback.items():
            if src in df.columns and dst not in rename.values():
                rename[src] = dst
        for src, dst in other.items():
            if src in df.columns and dst not in rename.values():
                rename[src] = dst
        return df.rename(columns=rename)

    df_model = _apply_col_map(df_model)

    for col in ["brand_code", "model_code"]:
        if col not in df_model.columns:
            raise HTTPException(status_code=422, detail="「型号」sheet 缺少必要列（品牌/品牌码 或 型号/型号码）")
        df_model[col] = df_model[col].replace("不需要填写", None).ffill()

    errors = []
    warnings = []
    preview = []
    valid_rows = 0
    total_rows = len(df_model)

    for idx, row in df_model.iterrows():
        row_num = int(idx) + 2  # Excel 行号（1=标题行）
        bc = _clean_val(row.get("brand_code"))
        mc = _clean_val(row.get("model_code"))
        if not bc or not mc:
            errors.append({"row": row_num, "message": "brand_code 或 model_code 为空，该行将被跳过"})
            continue

        launch_year = _clean_val(row.get("launch_year"))
        if launch_year and _to_int(launch_year) is None:
            warnings.append({"row": row_num, "message": f"上市年「{launch_year}」不是有效数字，将置为空"})

        valid_rows += 1
        if len(preview) < 10:
            preview.append({
                "brand_code":    str(bc),
                "model_code":    str(mc),
                "brand_name":    str(_clean_val(row.get("brand_name")) or bc),
                "model_name":    str(_clean_val(row.get("model_name")) or mc),
                "category_name": str(_clean_val(row.get("category_name")) or ""),
                "launch_year":   _to_int(_clean_val(row.get("launch_year"))),
                "launch_month":  _to_int(_clean_val(row.get("launch_month"))),
                "launch_price":  _to_float(_clean_val(row.get("launch_price"))),
            })

    spec_rows = 0
    if not df_spec.empty:
        df_spec.columns = [str(c).strip() for c in df_spec.columns]
        df_spec = _apply_col_map(df_spec.dropna(axis=1, how="all"))
        if "brand_code" in df_spec.columns and "model_code" in df_spec.columns:
            for col in ["brand_code", "model_code"]:
                df_spec[col] = df_spec[col].replace("不需要填写", None).ffill()
            for _, srow in df_spec.iterrows():
                if _clean_val(srow.get("spec_name")):
                    spec_rows += 1

    return {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "spec_rows":  spec_rows,
        "preview":    preview,
        "errors":     errors,
        "warnings":   warnings,
    }


@router.post("/preview", response_model=dict)
async def preview_models(file: UploadFile = File(...)):
    """解析 Excel 并返回预览数据，不写入数据库"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls 格式文件")
    content = await file.read()
    return _parse_models_file(content)


@router.post("/import", response_model=dict)
async def import_models(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    从 Excel 导入型号及规格。
    读取「型号」sheet 和「型号规格」sheet。
    唯一键为 (brand_code, model_code)，重复导入为更新。
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls 格式文件")

    content = await file.read()

    try:
        df_model = pd.read_excel(io.BytesIO(content), sheet_name="型号", dtype=str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"读取「型号」sheet 失败: {e}")

    try:
        df_spec = pd.read_excel(io.BytesIO(content), sheet_name="型号规格", dtype=str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"读取「型号规格」sheet 失败: {e}")

    df_model.columns = [str(c).strip() for c in df_model.columns]
    df_spec.columns  = [str(c).strip() for c in df_spec.columns]
    df_model = df_model.dropna(axis=1, how="all")
    df_spec  = df_spec.dropna(axis=1, how="all")

    # 列映射：优先「品牌码/型号码」，否则用「品牌/型号」
    def _apply_col_map(df):
        priority = {"品牌码": "brand_code", "型号码": "model_code"}
        fallback = {"品牌":   "brand_code", "型号":   "model_code"}
        other    = {
            "品类": "category_name",
            "上市年": "launch_year", "上市月": "launch_month", "上市周": "launch_week",
            "上市价格": "launch_price", "网址": "url",
            "规格名称": "spec_name", "规格值": "spec_value",
        }
        rename = {}
        for src, dst in priority.items():
            if src in df.columns:
                rename[src] = dst
        for src, dst in fallback.items():
            if src in df.columns and dst not in rename.values():
                rename[src] = dst
        for src, dst in other.items():
            if src in df.columns and dst not in rename.values():
                rename[src] = dst
        return df.rename(columns=rename)

    df_model = _apply_col_map(df_model)
    df_spec  = _apply_col_map(df_spec)

    for col in ["brand_code", "model_code"]:
        if col not in df_model.columns:
            raise HTTPException(status_code=422, detail=f"「型号」sheet 缺少必要列（品牌/品牌码 或 型号/型号码）")

    # 向下填充：品牌/型号列通常只有第一行有值
    for col in ["brand_code", "model_code"]:
        df_model[col] = df_model[col].replace("不需要填写", None).ffill()
    if "brand_code" in df_spec.columns:
        df_spec["brand_code"] = df_spec["brand_code"].replace("不需要填写", None).ffill()
    if "model_code" in df_spec.columns:
        df_spec["model_code"] = df_spec["model_code"].replace("不需要填写", None).ffill()

    upserted_models = 0
    model_key_to_id: dict[tuple, int] = {}

    for _, row in df_model.iterrows():
        bc = _clean_val(row.get("brand_code"))
        mc = _clean_val(row.get("model_code"))
        if not bc or not mc:
            continue

        vals = {
            "brand_code":    str(bc),
            "model_code":    str(mc),
            "category_name": str(_clean_val(row.get("category_name")) or ""),
            "brand_name":    str(_clean_val(row.get("brand_name"))    or bc),
            "model_name":    str(_clean_val(row.get("model_name"))    or mc),
            "launch_year":   _to_int(_clean_val(row.get("launch_year"))),
            "launch_month":  _to_int(_clean_val(row.get("launch_month"))),
            "launch_week":   _to_int(_clean_val(row.get("launch_week"))),
            "launch_price":  _to_float(_clean_val(row.get("launch_price"))),
            "url":           str(_clean_val(row.get("url")) or "") or None,
        }

        stmt = mysql_insert(ModelRecord).values(**vals)
        stmt = stmt.on_duplicate_key_update(
            category_name=stmt.inserted.category_name,
            brand_name=stmt.inserted.brand_name,
            model_name=stmt.inserted.model_name,
            launch_year=stmt.inserted.launch_year,
            launch_month=stmt.inserted.launch_month,
            launch_week=stmt.inserted.launch_week,
            launch_price=stmt.inserted.launch_price,
            url=stmt.inserted.url,
            updated_at=func.now(),
        )
        db.execute(stmt)
        upserted_models += 1

    db.flush()

    # 建立 (brand_code, model_code) -> model_id 映射
    for record in db.query(ModelRecord).all():
        model_key_to_id[(record.brand_code, record.model_code)] = record.id

    # 处理「型号规格」sheet
    upserted_specs = 0
    if "brand_code" in df_spec.columns and "model_code" in df_spec.columns:
        affected_model_ids: set[int] = set()
        spec_rows: list[dict] = []

        for _, row in df_spec.iterrows():
            bc = _clean_val(row.get("brand_code"))
            mc = _clean_val(row.get("model_code"))
            sn = _clean_val(row.get("spec_name"))
            if not bc or not mc or not sn:
                continue
            model_id = model_key_to_id.get((str(bc), str(mc)))
            if model_id is None:
                continue
            affected_model_ids.add(model_id)
            spec_rows.append({
                "model_id":   model_id,
                "spec_name":  str(sn).strip(),
                "spec_value": str(_clean_val(row.get("spec_value")) or "") or None,
            })

        if affected_model_ids:
            db.query(ModelSpec).filter(
                ModelSpec.model_id.in_(affected_model_ids)
            ).delete(synchronize_session=False)
        for s in spec_rows:
            db.add(ModelSpec(**s))
            upserted_specs += 1

    db.commit()
    return {"imported_models": upserted_models, "imported_specs": upserted_specs}


@router.get("", response_model=PaginatedResponse)
def list_models(
    brand_code: Optional[str] = Query(None),
    keyword:    Optional[str] = Query(None),
    page:       int = Query(1, ge=1),
    page_size:  int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(ModelRecord)
    if brand_code:
        q = q.filter(ModelRecord.brand_code.ilike(f"%{brand_code}%"))
    if keyword:
        q = q.filter(
            ModelRecord.model_name.ilike(f"%{keyword}%") |
            ModelRecord.model_code.ilike(f"%{keyword}%") |
            ModelRecord.brand_name.ilike(f"%{keyword}%")
        )

    total = q.count()
    items = q.order_by(ModelRecord.brand_code, ModelRecord.model_code) \
             .offset((page - 1) * page_size).limit(page_size).all()

    result = []
    for m in items:
        out = ModelOut.model_validate(m)
        out.specs = []
        result.append(out)

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=result)


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db)):
    obj = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="型号不存在")
    return ModelOut.model_validate(obj)


@router.post("", response_model=ModelOut)
def create_model(payload: ModelIn, db: Session = Depends(get_db)):
    existing = db.query(ModelRecord).filter(
        ModelRecord.brand_code == payload.brand_code,
        ModelRecord.model_code == payload.model_code,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该品牌+型号已存在")

    obj = ModelRecord(
        brand_code=payload.brand_code,
        model_code=payload.model_code,
        category_name=payload.category_name,
        brand_name=payload.brand_name,
        model_name=payload.model_name,
        launch_year=payload.launch_year,
        launch_month=payload.launch_month,
        launch_week=payload.launch_week,
        launch_price=payload.launch_price,
        url=payload.url,
    )
    db.add(obj)
    db.flush()

    for s in payload.specs:
        db.add(ModelSpec(model_id=obj.id, spec_name=s.spec_name, spec_value=s.spec_value))

    db.commit()
    db.refresh(obj)
    return ModelOut.model_validate(obj)


@router.put("/{model_id}", response_model=ModelOut)
def update_model(model_id: int, payload: ModelIn, db: Session = Depends(get_db)):
    obj = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="型号不存在")

    obj.brand_code    = payload.brand_code
    obj.model_code    = payload.model_code
    obj.category_name = payload.category_name
    obj.brand_name    = payload.brand_name
    obj.model_name    = payload.model_name
    obj.launch_year   = payload.launch_year
    obj.launch_month  = payload.launch_month
    obj.launch_week   = payload.launch_week
    obj.launch_price  = payload.launch_price
    obj.url           = payload.url

    db.query(ModelSpec).filter(ModelSpec.model_id == model_id).delete()
    for s in payload.specs:
        db.add(ModelSpec(model_id=model_id, spec_name=s.spec_name, spec_value=s.spec_value))

    db.commit()
    db.refresh(obj)
    return ModelOut.model_validate(obj)


@router.delete("/{model_id}")
def delete_model(model_id: int, db: Session = Depends(get_db)):
    obj = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="型号不存在")
    db.delete(obj)
    db.commit()
    return {"message": "已删除"}


# ─── 别名 CRUD ────────────────────────────────────────────────

from pydantic import BaseModel as _BaseModel


class _AliasIn(_BaseModel):
    alias_code: str


@router.get("/{model_id}/aliases", response_model=list[ModelAliasOut])
def list_aliases(model_id: int, db: Session = Depends(get_db)):
    obj = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="型号不存在")
    return obj.aliases


@router.post("/{model_id}/aliases", response_model=ModelAliasOut)
def add_alias(model_id: int, payload: _AliasIn, db: Session = Depends(get_db)):
    obj = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="型号不存在")
    code = payload.alias_code.strip()
    if not code:
        raise HTTPException(status_code=422, detail="alias_code 不能为空")
    existing = db.query(ModelAlias).filter(ModelAlias.alias_code == code).first()
    if existing:
        raise HTTPException(status_code=409, detail=f"别名「{code}」已存在")
    alias = ModelAlias(model_id=model_id, alias_code=code)
    db.add(alias)
    db.commit()
    db.refresh(alias)
    return alias


@router.delete("/{model_id}/aliases/{alias_id}")
def delete_alias(model_id: int, alias_id: int, db: Session = Depends(get_db)):
    alias = db.query(ModelAlias).filter(
        ModelAlias.id == alias_id,
        ModelAlias.model_id == model_id,
    ).first()
    if not alias:
        raise HTTPException(status_code=404, detail="别名不存在")
    db.delete(alias)
    db.commit()
    return {"message": "已删除"}
