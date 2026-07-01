"""
型号管理 API
支持 Excel 导入（型号 + 型号规格两个 sheet）、分页查询、增删改查
唯一键：brand_code + model_code
"""
import io
import os
import math
from urllib.parse import quote
import pandas as pd
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query, Response
from pydantic import BaseModel
from sqlalchemy.orm import Session
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy import func
from app.models.database import get_db
from app.models.schemas import (
    BrandRecord, ModelRecord, ModelSpec, ModelAlias,
    ModelIn, ModelOut, ModelSpecOut, ModelAliasOut,
    PaginatedResponse, Category,
)
from app.services.import_helper import save_tmp_file, read_columns, find_best_template, col_fingerprint

router = APIRouter(prefix="/api/models", tags=["models"])

UPLOAD_DIR = os.environ.get("UPLOAD_DIR", "./uploads")

_MODEL_TEMPLATE_FILENAME = "产品属性导入模板.xlsx"
_MODEL_TEMPLATE_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
_MODEL_TEMPLATE_HEADERS = ["品牌码", "型号码", "品类", "品牌名称", "型号名称", "上市年", "上市月", "上市周", "上市价格", "网址"]
_MODEL_SPEC_TEMPLATE_HEADERS = ["品牌码", "型号码", "规格名称", "规格值"]
_MODEL_TEMPLATE_MAPPING = {
    "品牌码": "brand_code",
    "型号码": "model_code",
    "品类": "category_code",
    "品牌名称": "brand_name",
    "型号名称": "model_name",
    "上市年": "launch_year",
    "上市月": "launch_month",
    "上市周": "launch_week",
    "上市价格": "launch_price",
    "网址": "url",
}


def _build_model_template_bytes() -> bytes:
    from openpyxl import Workbook

    workbook = Workbook()
    model_sheet = workbook.active
    model_sheet.title = "型号"
    model_sheet.append(_MODEL_TEMPLATE_HEADERS)
    model_sheet.append(["DJI", "OSMO-ACTION-4", "action_camera", "大疆", "Osmo Action 4", 2024, 9, None, 2999, "https://example.com/product"])

    spec_sheet = workbook.create_sheet("型号规格")
    spec_sheet.append(_MODEL_SPEC_TEMPLATE_HEADERS)
    spec_sheet.append(["DJI", "OSMO-ACTION-4", "产品形态", "OA传统"])

    output = io.BytesIO()
    workbook.save(output)
    return output.getvalue()


class ModelsConfirmPayload(BaseModel):
    temp_file_id: str
    mapping: dict
    ignore_columns: list = []
    category_code: str
    save_template_name: Optional[str] = None


@router.post("/headers")
async def models_headers(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
):
    """P10: Step 1 — read columns from model sheet, suggest template."""
    temp_file_id, save_path, filename = await save_tmp_file(file, UPLOAD_DIR)
    columns = read_columns(save_path)
    if columns == _MODEL_TEMPLATE_HEADERS:
        best_tmpl = None
        score = 100
        suggested_template = {
            "id": 0,
            "name": "产品属性导入模板",
            "mapping": _MODEL_TEMPLATE_MAPPING,
            "ignore_columns": [],
        }
    else:
        best_tmpl, score = find_best_template(columns, "model", db)
        suggested_template = {
            "id": best_tmpl.id,
            "name": best_tmpl.name,
            "mapping": best_tmpl.mapping,
            "ignore_columns": best_tmpl.ignore_columns or [],
        } if best_tmpl else None
    return {
        "temp_file_id": temp_file_id,
        "filename": filename,
        "columns": columns,
        "suggested_template": suggested_template,
        "match_score": score,
    }


@router.post("/confirm")
def models_confirm(
    payload: ModelsConfirmPayload,
    db: Session = Depends(get_db),
):
    """P10: Step 2 — parse model sheet with mapping, upsert models."""
    tmp_dir = Path(UPLOAD_DIR) / "tmp"
    # Find temp file (may have uuid prefix)
    candidates = list(tmp_dir.glob(f"*{payload.temp_file_id}*")) if tmp_dir.exists() else []
    if not candidates:
        direct = tmp_dir / payload.temp_file_id
        if direct.exists():
            candidates = [direct]
    if not candidates:
        raise HTTPException(status_code=404, detail="Temp file not found or expired")
    file_path = candidates[0]

    suffix = file_path.suffix.lower()
    df_spec = pd.DataFrame()
    if suffix == ".csv":
        try:
            df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig")
        except Exception:
            df = pd.read_csv(file_path, dtype=str, encoding="gbk")
    else:
        df = pd.read_excel(file_path, sheet_name=0, dtype=str)
        try:
            df_spec = pd.read_excel(file_path, sheet_name="型号规格", dtype=str)
        except Exception:
            df_spec = pd.DataFrame()
    df.columns = [str(c).strip() for c in df.columns]

    ignore_set = set(payload.ignore_columns)
    rename_map = {
        col: target
        for col, target in payload.mapping.items()
        if col in df.columns and col not in ignore_set
    }
    df = df.rename(columns=rename_map)

    models_inserted = 0
    models_updated = 0
    errors = []

    for i, row in enumerate(df.itertuples(index=False), start=2):
        row_dict = row._asdict()

        brand_code = str(row_dict.get("brand_code") or "").strip()
        model_code = str(row_dict.get("model_code") or "").strip()
        if not brand_code or not model_code:
            errors.append(f"Row {i}: missing brand_code or model_code")
            continue

        # category_code: from Excel if present and non-empty, else fallback
        cat_val = str(row_dict.get("category_code") or "").strip()
        category_code = cat_val if cat_val else payload.category_code

        optional_fields = {
            k: str(row_dict.get(k) or "").strip() or None
            for k in ["brand_name", "model_name", "url"]
        }
        existing = (
            db.query(ModelRecord)
            .filter(ModelRecord.brand_code == brand_code, ModelRecord.model_code == model_code)
            .first()
        )
        _ensure_import_brand(db, brand_code, optional_fields.get("brand_name"))
        int_fields = {}
        for k in ["launch_year", "launch_month", "launch_week"]:
            v = row_dict.get(k)
            try:
                int_fields[k] = int(str(v).strip()) if v and str(v).strip() else None
            except (ValueError, TypeError):
                int_fields[k] = None
        price_raw = row_dict.get("launch_price")
        try:
            launch_price = float(str(price_raw).strip()) if price_raw and str(price_raw).strip() else None
        except (ValueError, TypeError):
            launch_price = None

        if existing:
            for attr, val in {**optional_fields, **int_fields, "launch_price": launch_price, "category_code": category_code}.items():
                if val is not None:
                    setattr(existing, attr, val)
            models_updated += 1
        else:
            db.add(ModelRecord(
                brand_code=brand_code,
                model_code=model_code,
                category_code=category_code,
                **optional_fields,
                **int_fields,
                launch_price=launch_price,
            ))
            models_inserted += 1

    specs_inserted = 0
    if models_inserted > 0 or models_updated > 0:
        db.flush()

        model_key_to_id = {
            (record.brand_code, record.model_code): record.id
            for record in db.query(ModelRecord).all()
        }

        if not df_spec.empty:
            df_spec.columns = [str(c).strip() for c in df_spec.columns]
            df_spec = df_spec.dropna(axis=1, how="all")
            priority = {"品牌码": "brand_code", "型号码": "model_code"}
            fallback = {"品牌": "brand_code", "型号": "model_code"}
            other = {"规格名称": "spec_name", "规格值": "spec_value"}
            spec_rename = {}
            for src, dst in priority.items():
                if src in df_spec.columns:
                    spec_rename[src] = dst
            for src, dst in fallback.items():
                if src in df_spec.columns and dst not in spec_rename.values():
                    spec_rename[src] = dst
            for src, dst in other.items():
                if src in df_spec.columns and dst not in spec_rename.values():
                    spec_rename[src] = dst
            df_spec = df_spec.rename(columns=spec_rename)

            if "brand_code" in df_spec.columns and "model_code" in df_spec.columns:
                for col in ["brand_code", "model_code"]:
                    df_spec[col] = df_spec[col].replace("不需要填写", None).ffill()

                affected_model_ids = set()
                spec_rows = []
                for _, spec_row in df_spec.iterrows():
                    brand_code = _clean_val(spec_row.get("brand_code"))
                    model_code = _clean_val(spec_row.get("model_code"))
                    spec_name = _clean_val(spec_row.get("spec_name"))
                    if not brand_code or not model_code or not spec_name:
                        continue
                    model_id = model_key_to_id.get((str(brand_code), str(model_code)))
                    if model_id is None:
                        continue
                    affected_model_ids.add(model_id)
                    spec_rows.append({
                        "model_id": model_id,
                        "spec_name": str(spec_name).strip(),
                        "spec_value": str(_clean_val(spec_row.get("spec_value")) or "") or None,
                    })

                if affected_model_ids:
                    db.query(ModelSpec).filter(
                        ModelSpec.model_id.in_(affected_model_ids)
                    ).delete(synchronize_session=False)
                for spec in spec_rows:
                    db.add(ModelSpec(**spec))
                    specs_inserted += 1

        db.commit()

    if payload.save_template_name and (models_inserted + models_updated) > 0:
        from app.models.schemas import ColumnTemplate
        tmpl = ColumnTemplate(
            name=payload.save_template_name,
            module="model",
            mapping=payload.mapping,
            ignore_columns=payload.ignore_columns,
            col_fingerprint=col_fingerprint(list(payload.mapping.keys())),
        )
        db.add(tmpl)
        try:
            db.commit()
        except Exception:
            db.rollback()

    return {
        "models_inserted": models_inserted,
        "models_updated": models_updated,
        "specs_inserted": specs_inserted,
        "aliases_inserted": 0,
        "errors": errors,
    }


def _normalize_code(value: str | None) -> str:
    return (value or "").strip()


def _normalize_optional_text(value: str | None) -> str | None:
    cleaned = (value or "").strip()
    return cleaned or None


def _is_placeholder_code(value: str) -> bool:
    return not value or set(value) == {"-"}


def _ensure_import_brand(db: Session, brand_code: str, brand_name: str | None = None) -> None:
    """Keep batch import compatible by creating missing brand master rows."""
    normalized_code = _normalize_code(brand_code)
    if _is_placeholder_code(normalized_code):
        return
    existing = db.query(BrandRecord).filter(BrandRecord.brand_code == normalized_code).first()
    if existing:
        if not existing.brand_name and brand_name:
            existing.brand_name = _normalize_optional_text(brand_name)
        return
    db.add(BrandRecord(
        brand_code=normalized_code,
        brand_name=_normalize_optional_text(brand_name),
        status="active",
    ))


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
            "品类": "category_code", "品牌名称": "brand_name", "型号名称": "model_name",
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
                "category_code": str(_clean_val(row.get("category_code")) or "") or None,
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
            "品类": "category_code", "品牌名称": "brand_name", "型号名称": "model_name",
            "上市年": "launch_year", "上市月": "launch_month", "上市周": "launch_week",
            "上市价格": "launch_price", "网址": "url",
            "规格名称": "spec_name", "规格值": "spec_value",
            "别名": "alias_code",
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

    # 检测数据库方言，决定是否使用 MySQL ON DUPLICATE KEY UPDATE
    dialect_name = db.bind.dialect.name if hasattr(db, "bind") and db.bind else db.get_bind().dialect.name

    for _, row in df_model.iterrows():
        bc = _clean_val(row.get("brand_code"))
        mc = _clean_val(row.get("model_code"))
        if not bc or not mc:
            continue

        vals = {
            "brand_code":    str(bc),
            "model_code":    str(mc),
            "category_code": str(_clean_val(row.get("category_code")) or "") or None,
            "brand_name":    str(_clean_val(row.get("brand_name"))    or bc),
            "model_name":    str(_clean_val(row.get("model_name"))    or mc),
            "launch_year":   _to_int(_clean_val(row.get("launch_year"))),
            "launch_month":  _to_int(_clean_val(row.get("launch_month"))),
            "launch_week":   _to_int(_clean_val(row.get("launch_week"))),
            "launch_price":  _to_float(_clean_val(row.get("launch_price"))),
            "url":           str(_clean_val(row.get("url")) or "") or None,
        }

        _ensure_import_brand(db, vals["brand_code"], vals["brand_name"])

        if dialect_name == "mysql":
            stmt = mysql_insert(ModelRecord).values(**vals)
            stmt = stmt.on_duplicate_key_update(
                category_code=stmt.inserted.category_code,
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
        else:
            existing = db.query(ModelRecord).filter(
                ModelRecord.brand_code == vals["brand_code"],
                ModelRecord.model_code == vals["model_code"],
            ).first()
            if existing:
                for k, v in vals.items():
                    if k not in ("brand_code", "model_code"):
                        setattr(existing, k, v)
            else:
                db.add(ModelRecord(**vals))
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

    # 处理「别名」sheet（可选，无此 sheet 时静默跳过）
    upserted_aliases = 0
    try:
        df_alias = pd.read_excel(io.BytesIO(content), sheet_name="别名", dtype=str)
        df_alias.columns = [str(c).strip() for c in df_alias.columns]
        df_alias = _apply_col_map(df_alias.dropna(axis=1, how="all"))
        if "brand_code" in df_alias.columns and "model_code" in df_alias.columns and "alias_code" in df_alias.columns:
            for col in ["brand_code", "model_code"]:
                df_alias[col] = df_alias[col].replace("不需要填写", None).ffill()
            for _, arow in df_alias.iterrows():
                bc = _clean_val(arow.get("brand_code"))
                mc = _clean_val(arow.get("model_code"))
                ac = _clean_val(arow.get("alias_code"))
                if not bc or not mc or not ac:
                    continue
                model_id = model_key_to_id.get((str(bc), str(mc)))
                if model_id is None:
                    continue
                ac_str = str(ac).strip()
                if not ac_str:
                    continue
                exists = db.query(ModelAlias).filter(ModelAlias.alias_code == ac_str).first()
                if not exists:
                    db.add(ModelAlias(model_id=model_id, alias_code=ac_str))
                    upserted_aliases += 1
    except Exception:
        pass  # 无「别名」sheet 时静默跳过

    db.commit()
    return {"imported_models": upserted_models, "imported_specs": upserted_specs, "imported_aliases": upserted_aliases}


@router.get("/template")
def download_model_template():
    content = _build_model_template_bytes()
    quoted_filename = quote(_MODEL_TEMPLATE_FILENAME)
    headers = {"Content-Disposition": f"attachment; filename*=UTF-8''{quoted_filename}"}
    return Response(content=content, media_type=_MODEL_TEMPLATE_MEDIA_TYPE, headers=headers)


@router.get("", response_model=PaginatedResponse)
def list_models(
    brand_code:    Optional[str] = Query(None),
    keyword:       Optional[str] = Query(None),
    category_code: Optional[str] = Query(None),
    status:        Optional[str] = Query(None),
    page:          int = Query(1, ge=1),
    page_size:     int = Query(20, ge=1, le=2000),
    db: Session = Depends(get_db),
):
    # count query (no join needed)
    cq = db.query(ModelRecord)
    if brand_code:
        cq = cq.filter(ModelRecord.brand_code.ilike(f"%{brand_code}%"))
    if keyword:
        cq = cq.filter(
            ModelRecord.model_name.ilike(f"%{keyword}%") |
            ModelRecord.model_code.ilike(f"%{keyword}%") |
            ModelRecord.brand_name.ilike(f"%{keyword}%")
        )
    if category_code:
        cq = cq.filter(ModelRecord.category_code == category_code)
    if status:
        cq = cq.filter(ModelRecord.status == status)
    total = cq.count()

    q = db.query(ModelRecord, Category).outerjoin(
        Category, ModelRecord.category_code == Category.code
    )
    if brand_code:
        q = q.filter(ModelRecord.brand_code.ilike(f"%{brand_code}%"))
    if keyword:
        q = q.filter(
            ModelRecord.model_name.ilike(f"%{keyword}%") |
            ModelRecord.model_code.ilike(f"%{keyword}%") |
            ModelRecord.brand_name.ilike(f"%{keyword}%")
        )
    if category_code:
        q = q.filter(ModelRecord.category_code == category_code)
    if status:
        q = q.filter(ModelRecord.status == status)
    rows = q.order_by(ModelRecord.brand_code, ModelRecord.model_code) \
            .offset((page - 1) * page_size).limit(page_size).all()

    result = []
    for m, cat in rows:
        out = ModelOut.model_validate(m)
        out.category_name = cat.name if cat else None
        out.specs = []
        result.append(out)

    return PaginatedResponse(total=total, page=page, page_size=page_size, items=result)


@router.get("/{model_id}", response_model=ModelOut)
def get_model(model_id: int, db: Session = Depends(get_db)):
    row = db.query(ModelRecord, Category).outerjoin(
        Category, ModelRecord.category_code == Category.code
    ).filter(ModelRecord.id == model_id).first()
    if not row:
        raise HTTPException(status_code=404, detail="型号不存在")
    m, cat = row
    out = ModelOut.model_validate(m)
    out.category_name = cat.name if cat else None
    return out


@router.post("", response_model=ModelOut)
def create_model(payload: ModelIn, db: Session = Depends(get_db)):
    brand_code = _normalize_code(payload.brand_code)
    model_code = _normalize_code(payload.model_code)

    brand = db.query(BrandRecord).filter(BrandRecord.brand_code == brand_code).first()
    if not brand:
        raise HTTPException(status_code=400, detail="请先创建品牌或选择已有品牌")

    existing = db.query(ModelRecord).filter(
        ModelRecord.brand_code == brand_code,
        ModelRecord.model_code == model_code,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该品牌+型号已存在")

    obj = ModelRecord(
        brand_code=brand_code,
        model_code=model_code,
        category_code=payload.category_code,
        brand_name=_normalize_optional_text(payload.brand_name) or brand.brand_name,
        model_name=_normalize_optional_text(payload.model_name),
        launch_year=payload.launch_year,
        launch_month=payload.launch_month,
        launch_week=payload.launch_week,
        launch_price=payload.launch_price,
        url=payload.url,
        status=payload.status,
        operator=payload.operator,
    )
    db.add(obj)
    db.flush()

    for s in payload.specs:
        db.add(ModelSpec(model_id=obj.id, spec_name=s.spec_name, spec_value=s.spec_value))

    db.commit()
    db.refresh(obj)
    cat = db.query(Category).filter(Category.code == obj.category_code).first() if obj.category_code else None
    out = ModelOut.model_validate(obj)
    out.category_name = cat.name if cat else None
    return out


@router.put("/{model_id}", response_model=ModelOut)
def update_model(model_id: int, payload: ModelIn, db: Session = Depends(get_db)):
    obj = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="型号不存在")

    obj.brand_code    = payload.brand_code
    obj.model_code    = payload.model_code
    obj.category_code = payload.category_code
    obj.brand_name    = payload.brand_name
    obj.model_name    = payload.model_name
    obj.launch_year   = payload.launch_year
    obj.launch_month  = payload.launch_month
    obj.launch_week   = payload.launch_week
    obj.launch_price  = payload.launch_price
    obj.url           = payload.url
    obj.status        = payload.status
    obj.operator      = payload.operator

    db.query(ModelSpec).filter(ModelSpec.model_id == model_id).delete()
    for s in payload.specs:
        db.add(ModelSpec(model_id=model_id, spec_name=s.spec_name, spec_value=s.spec_value))

    db.commit()
    db.refresh(obj)
    cat = db.query(Category).filter(Category.code == obj.category_code).first() if obj.category_code else None
    out = ModelOut.model_validate(obj)
    out.category_name = cat.name if cat else None
    return out


@router.delete("/{model_id}")
def delete_model(model_id: int, db: Session = Depends(get_db)):
    obj = db.query(ModelRecord).filter(ModelRecord.id == model_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="型号不存在")
    db.delete(obj)
    db.commit()
    return {"message": "已删除"}


# ─── 别名 CRUD ────────────────────────────────────────────────

class _AliasIn(BaseModel):
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
