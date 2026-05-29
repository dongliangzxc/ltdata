"""
元数据规格管理 API
支持 Excel 导入、分页查询、增删改查
"""
import io
import math
from pathlib import Path
import pandas as pd
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Query
from fastapi.responses import FileResponse
from sqlalchemy.orm import Session
from sqlalchemy.dialects.mysql import insert as mysql_insert
from sqlalchemy import func
from app.models.database import get_db
from app.models.schemas import Category, MetadataSpec, MetadataSpecIn, MetadataSpecOut, PaginatedResponse

router = APIRouter(prefix="/api/metadata", tags=["metadata"])

_TEMPLATE_FILENAME = "洛图科技—产品段属性说明-模板.xlsx"
_METADATA_TEMPLATE_PATH = Path(__file__).resolve().parents[1] / "templates" / _TEMPLATE_FILENAME


def _clean_val(v):
    """清理 pandas 空值"""
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


def _match_category_code(db: Session, sheet_name: str) -> str:
    category = (
        db.query(Category)
        .filter((Category.code == sheet_name) | (Category.name == sheet_name))
        .first()
    )
    if not category:
        raise HTTPException(status_code=422, detail=f"找不到匹配品类：{sheet_name}，请确认 sheet 名是已有品类码或品类名称")
    return category.code


def _read_metadata_excel(content: bytes, db: Session | None = None) -> pd.DataFrame:
    try:
        workbook = pd.ExcelFile(io.BytesIO(content))
        sheet_name = "元数据" if "元数据" in workbook.sheet_names else workbook.sheet_names[0]
        df = pd.read_excel(workbook, sheet_name=sheet_name, dtype=str)
    except Exception as e:
        raise HTTPException(status_code=422, detail=f"读取产品字段定义 Excel 失败：{e}")

    df.columns = [str(c).strip() for c in df.columns]
    df = df.dropna(axis=1, how='all')
    if "category_code" not in df.columns and "品类码" not in df.columns and sheet_name != "元数据":
        if db is None:
            df["category_code"] = sheet_name
        else:
            df["category_code"] = _match_category_code(db, sheet_name)
    return df


def _normalize_metadata_columns(df: pd.DataFrame) -> pd.DataFrame:
    col_map = {
        "品类码": "category_code", "规格名称": "spec_name",
        "规格类型": "spec_type",   "规格值": "spec_value_raw",
        "必填": "required_raw",   "保留几位小数": "decimal_places_raw",
        "单选": "single_select_raw",
        "属性字段名称": "spec_name", "字段类型": "spec_type",
        "字段内容实例": "spec_value_raw", "字段说明": "single_select_raw",
    }
    return df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})


def _parse_metadata_file(content: bytes, db: Session | None = None) -> dict:
    """解析 Excel，返回预览数据，不操作数据库"""
    df = _normalize_metadata_columns(_read_metadata_excel(content, db))

    for col in ["spec_name", "spec_type"]:
        if col not in df.columns:
            raise HTTPException(status_code=422, detail=f"缺少必要列（找不到「{col}」对应列）")

    if "category_code" not in df.columns:
        df["category_code"] = ""
    else:
        df["category_code"] = df["category_code"].replace("不需要填写", None).ffill().fillna("")

    errors = []
    warnings = []
    preview = []
    valid_rows = 0
    total_rows = len(df)

    for idx, row in df.iterrows():
        row_num = int(idx) + 2
        spec_name = _clean_val(row.get("spec_name"))
        if not spec_name:
            errors.append({"row": row_num, "message": "规格名称为空，该行将被跳过"})
            continue

        spec_type = str(_clean_val(row.get("spec_type")) or "文本型").strip()
        valid_spec_types = {"数值型", "文本型", "布尔型"}
        if spec_type not in valid_spec_types:
            warnings.append({"row": row_num, "message": f"规格类型「{spec_type}」不在预设值内，将原样保存"})

        valid_rows += 1
        if len(preview) < 10:
            preview.append({
                "category_code": str(_clean_val(row.get("category_code")) or ""),
                "spec_name":     str(spec_name).strip(),
                "spec_type":     spec_type,
                "spec_values":   str(_clean_val(row.get("spec_value_raw")) or "") or None,
                "required":      str(_clean_val(row.get("required_raw")) or "") in ("是", "1", "True", "true", "YES"),
            })

    return {
        "total_rows": total_rows,
        "valid_rows": valid_rows,
        "preview":    preview,
        "errors":     errors,
        "warnings":   warnings,
    }


@router.post("/preview", response_model=dict)
async def preview_metadata(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """解析 Excel 并返回预览数据，不写入数据库"""
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls 格式文件")
    content = await file.read()
    return _parse_metadata_file(content, db)


@router.post("/import", response_model=dict)
async def import_metadata(file: UploadFile = File(...), db: Session = Depends(get_db)):
    """
    从 Excel 导入元数据。
    读取「元数据」sheet，同一 category_code+spec_name 的多行 spec_values 合并为逗号分隔，
    然后 upsert 入库。
    """
    if not file.filename.endswith((".xlsx", ".xls")):
        raise HTTPException(status_code=400, detail="只支持 .xlsx / .xls 格式文件")

    content = await file.read()
    df = _normalize_metadata_columns(_read_metadata_excel(content, db))

    for col in ["spec_name", "spec_type"]:
        if col not in df.columns:
            raise HTTPException(status_code=422, detail=f"缺少必要列，请检查 Excel 格式（找不到对应列）")

    # 模版中 品类码 列可能全为"不需要填写"或 NaN，用固定值 "SB" 兜底
    # 如果有有效值则使用，否则设为空字符串后统一用规格名唯一
    if "category_code" not in df.columns:
        df["category_code"] = ""
    else:
        # "不需要填写" 当作空处理，用 ffill 填充
        df["category_code"] = df["category_code"].replace("不需要填写", None)
        df["category_code"] = df["category_code"].ffill().fillna("")

    rows_to_upsert = []
    for _, row in df.iterrows():
        spec_name = _clean_val(row.get("spec_name"))
        if not spec_name:
            continue

        category_code = str(_clean_val(row.get("category_code")) or "").strip()
        spec_type = str(_clean_val(row.get("spec_type")) or "文本型").strip()

        # 规格值：模版里已经是逗号合并的一行，直接取
        spec_values = _clean_val(row.get("spec_value_raw"))
        spec_values = str(spec_values).strip() if spec_values is not None else None

        # 必填
        req_raw = str(_clean_val(row.get("required_raw")) or "").strip()
        required = 1 if req_raw in ("是", "1", "True", "true", "YES", "yes") else 0

        # 小数位
        dp_raw = _clean_val(row.get("decimal_places_raw"))
        try:
            decimal_places = int(float(dp_raw)) if dp_raw is not None else None
        except (ValueError, TypeError):
            decimal_places = None

        # 单选
        ss_raw = str(_clean_val(row.get("single_select_raw")) or "").strip()
        single_select = 0 if ss_raw in ("否", "0", "False", "false", "NO", "no") else 1

        rows_to_upsert.append({
            "category_code": category_code,
            "spec_name":     str(spec_name).strip(),
            "spec_type":     spec_type,
            "spec_values":   spec_values,
            "required":      required,
            "decimal_places": decimal_places,
            "single_select": single_select,
        })

    if not rows_to_upsert:
        return {"imported": 0, "upserted": 0}

    upserted = 0
    for row in rows_to_upsert:
        stmt = mysql_insert(MetadataSpec).values(**row)
        stmt = stmt.on_duplicate_key_update(
            spec_type=stmt.inserted.spec_type,
            spec_values=stmt.inserted.spec_values,
            required=stmt.inserted.required,
            decimal_places=stmt.inserted.decimal_places,
            single_select=stmt.inserted.single_select,
            updated_at=func.now(),
        )
        db.execute(stmt)
        upserted += 1

    db.commit()
    return {"imported": len(rows_to_upsert), "upserted": upserted}


@router.get("/template")
def download_metadata_template():
    if not _METADATA_TEMPLATE_PATH.exists():
        raise HTTPException(status_code=404, detail="模板文件不存在")
    return FileResponse(
        path=str(_METADATA_TEMPLATE_PATH),
        filename=_TEMPLATE_FILENAME,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@router.get("", response_model=PaginatedResponse)
def list_metadata(
    category_code: Optional[str] = Query(None),
    spec_name: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=200),
    db: Session = Depends(get_db),
):
    q = db.query(MetadataSpec)
    if category_code:
        q = q.filter(MetadataSpec.category_code.ilike(f"%{category_code}%"))
    if spec_name:
        q = q.filter(MetadataSpec.spec_name.ilike(f"%{spec_name}%"))

    total = q.count()
    items = q.order_by(MetadataSpec.category_code, MetadataSpec.spec_name)\
             .offset((page - 1) * page_size).limit(page_size).all()

    return PaginatedResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[MetadataSpecOut.model_validate(r) for r in items],
    )


@router.post("", response_model=MetadataSpecOut)
def create_metadata(payload: MetadataSpecIn, db: Session = Depends(get_db)):
    existing = db.query(MetadataSpec).filter(
        MetadataSpec.category_code == payload.category_code,
        MetadataSpec.spec_name == payload.spec_name,
    ).first()
    if existing:
        raise HTTPException(status_code=409, detail="该品类码+规格名称已存在")

    obj = MetadataSpec(
        category_code=payload.category_code,
        spec_name=payload.spec_name,
        spec_type=payload.spec_type,
        spec_values=payload.spec_values,
        required=1 if payload.required else 0,
        decimal_places=payload.decimal_places,
        single_select=1 if payload.single_select else 0,
    )
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return MetadataSpecOut.model_validate(obj)


@router.put("/{spec_id}", response_model=MetadataSpecOut)
def update_metadata(spec_id: int, payload: MetadataSpecIn, db: Session = Depends(get_db)):
    obj = db.query(MetadataSpec).filter(MetadataSpec.id == spec_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="记录不存在")

    obj.category_code  = payload.category_code
    obj.spec_name      = payload.spec_name
    obj.spec_type      = payload.spec_type
    obj.spec_values    = payload.spec_values
    obj.required       = 1 if payload.required else 0
    obj.decimal_places = payload.decimal_places
    obj.single_select  = 1 if payload.single_select else 0
    db.commit()
    db.refresh(obj)
    return MetadataSpecOut.model_validate(obj)


@router.delete("/{spec_id}")
def delete_metadata(spec_id: int, db: Session = Depends(get_db)):
    obj = db.query(MetadataSpec).filter(MetadataSpec.id == spec_id).first()
    if not obj:
        raise HTTPException(status_code=404, detail="记录不存在")
    db.delete(obj)
    db.commit()
    return {"message": "已删除"}
