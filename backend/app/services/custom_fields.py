"""品类清洗扩展字段服务。

字段配置存 ``category_custom_fields``，人工填写的条目值存
``match_result_extra_values``；自动值/默认值不落库，读取时实时计算，
这样调整关键词或默认值后无需重跑清洗。
"""
from __future__ import annotations

from typing import Iterable, Optional

from sqlalchemy.orm import Session

from app.models.schemas import (
    CategoryCustomField,
    CleanJobRecord,
    MatchResult,
    MatchResultExtraValue,
    ModelRecord,
)


def split_values(raw: Optional[str]) -> list[str]:
    """按逗号/中文逗号/换行拆分配置值。"""
    if not raw:
        return []
    text = str(raw).replace(",", "\n").replace("，", "\n").replace("、", "\n")
    return [part.strip() for part in text.splitlines() if part.strip()]


def load_fields_by_category(
    db: Session,
    category_codes: Optional[Iterable[str]] = None,
    *,
    export_only: bool = False,
) -> dict[str, list[CategoryCustomField]]:
    """返回 {category_code: [字段定义]}，仅 active 字段。"""
    q = db.query(CategoryCustomField).filter(CategoryCustomField.is_active == 1)
    if category_codes is not None:
        codes = {str(code) for code in category_codes if code}
        if not codes:
            return {}
        q = q.filter(CategoryCustomField.category_code.in_(codes))
    if export_only:
        q = q.filter(CategoryCustomField.export == 1)
    rows = q.order_by(
        CategoryCustomField.category_code,
        CategoryCustomField.sort_order,
        CategoryCustomField.id,
    ).all()
    result: dict[str, list[CategoryCustomField]] = {}
    for row in rows:
        result.setdefault(row.category_code, []).append(row)
    return result


def load_all_export_fields(db: Session) -> list[CategoryCustomField]:
    """导出用：全部品类的 active 且 export=1 字段，按 field_key 去重。"""
    rows = (
        db.query(CategoryCustomField)
        .filter(
            CategoryCustomField.is_active == 1,
            CategoryCustomField.export == 1,
        )
        .order_by(CategoryCustomField.sort_order, CategoryCustomField.id)
        .all()
    )
    seen: set[str] = set()
    result: list[CategoryCustomField] = []
    for row in rows:
        if row.field_key in seen:
            continue
        seen.add(row.field_key)
        result.append(row)
    return result


def _auto_value(field: CategoryCustomField, item_name: Optional[str]) -> Optional[str]:
    if not field.auto_keywords or field.auto_value is None:
        return None
    haystack = (item_name or "").casefold()
    if not haystack:
        return None
    for keyword in split_values(field.auto_keywords):
        if keyword.casefold() in haystack:
            return field.auto_value
    return None


def _default_value(field: CategoryCustomField) -> Optional[str]:
    value = (field.default_value or "").strip()
    return value or None


def _load_stored_values(
    db: Session,
    match_result_ids: Iterable[int],
) -> dict[tuple[int, str], MatchResultExtraValue]:
    ids = [int(mid) for mid in match_result_ids if mid is not None]
    if not ids:
        return {}
    rows = (
        db.query(MatchResultExtraValue)
        .filter(MatchResultExtraValue.match_result_id.in_(ids))
        .all()
    )
    return {(row.match_result_id, row.field_key): row for row in rows}


def resolve_effective_values(
    db: Session,
    items: Iterable[dict],
    fields_by_category: Optional[dict[str, list[CategoryCustomField]]] = None,
) -> dict[int, dict[str, dict]]:
    """计算一批条目的扩展字段最终值。

    items 每项需包含：``match_result_id``、``category_code``、``item_name``。
    返回 ``{match_result_id: {field_key: {"value": ..., "source": "manual|auto|default|none"}}}``。
    """
    normalized = [
        {
            "match_result_id": int(item["match_result_id"]),
            "category_code": item.get("category_code") or "",
            "item_name": item.get("item_name"),
        }
        for item in items
        if item.get("match_result_id") is not None
    ]
    if not normalized:
        return {}

    if fields_by_category is None:
        fields_by_category = load_fields_by_category(
            db, {item["category_code"] for item in normalized}
        )
    stored = _load_stored_values(db, [item["match_result_id"] for item in normalized])

    result: dict[int, dict[str, dict]] = {}
    for item in normalized:
        per_item: dict[str, dict] = {}
        for field in fields_by_category.get(item["category_code"], []):
            manual = stored.get((item["match_result_id"], field.field_key))
            if manual is not None:
                per_item[field.field_key] = {
                    "value": manual.field_value,
                    "source": manual.source or "manual",
                }
                continue
            auto = _auto_value(field, item["item_name"])
            if auto is not None:
                per_item[field.field_key] = {"value": auto, "source": "auto"}
                continue
            default = _default_value(field)
            if default is not None:
                per_item[field.field_key] = {"value": default, "source": "default"}
            else:
                per_item[field.field_key] = {"value": None, "source": "none"}
        result[item["match_result_id"]] = per_item
    return result


def get_match_category_code(db: Session, mr: MatchResult) -> Optional[str]:
    """取匹配结果对应品类：优先型号品类，其次清洗任务品类。"""
    if mr.model_id:
        model = db.query(ModelRecord).filter(ModelRecord.id == mr.model_id).first()
        if model and model.category_code:
            return model.category_code
    job = db.query(CleanJobRecord).filter(CleanJobRecord.id == mr.clean_job_id).first()
    if job:
        return job.category_code or job.dispatch_category_code
    return None


def get_review_fields(
    db: Session,
    mr: MatchResult,
    category_code: Optional[str],
    item_name: Optional[str],
) -> list[dict]:
    """复核详情用：返回当前条目的扩展字段定义 + 最终值。"""
    if not category_code:
        return []
    fields = load_fields_by_category(db, [category_code]).get(category_code, [])
    if not fields:
        return []
    values = resolve_effective_values(
        db,
        [{
            "match_result_id": mr.id,
            "category_code": category_code,
            "item_name": item_name,
        }],
        {category_code: fields},
    ).get(mr.id, {})
    result = []
    for field in fields:
        info = values.get(field.field_key, {"value": None, "source": "none"})
        result.append({
            "field_key": field.field_key,
            "field_label": field.field_label,
            "field_type": field.field_type,
            "options": split_values(field.options),
            "required": bool(field.required),
            "value": info["value"],
            "source": info["source"],
        })
    return result


def _normalize_manual_value(field: CategoryCustomField, value: Optional[str]) -> Optional[str]:
    text = (value or "").strip()
    if not text:
        return None
    if field.field_type == "enum":
        options = split_values(field.options)
        if options and text not in options:
            raise ValueError(f"字段「{field.field_label}」只能取：{' / '.join(options)}")
    elif field.field_type == "bool":
        lowered = text.casefold()
        if lowered in {"true", "1", "yes", "y"}:
            return "是"
        if lowered in {"false", "0", "no", "n"}:
            return "否"
        if text not in {"是", "否"}:
            raise ValueError(f"字段「{field.field_label}」只能取：是 / 否")
    elif field.field_type == "number":
        try:
            float(text)
        except ValueError as exc:
            raise ValueError(f"字段「{field.field_label}」必须是数字") from exc
    return text


def set_manual_value(
    db: Session,
    mr: MatchResult,
    category_code: Optional[str],
    field_key: str,
    value: Optional[str],
    *,
    commit: bool = True,
) -> dict:
    """写入/清除人工值。value 为空时删除人工覆盖，回退到自动值/默认值。"""
    if not category_code:
        raise ValueError("当前条目缺少品类，无法设置扩展字段")
    field = (
        db.query(CategoryCustomField)
        .filter(
            CategoryCustomField.category_code == category_code,
            CategoryCustomField.field_key == field_key,
            CategoryCustomField.is_active == 1,
        )
        .first()
    )
    if not field:
        raise ValueError("扩展字段不存在或已停用")

    normalized = _normalize_manual_value(field, value)
    existing = (
        db.query(MatchResultExtraValue)
        .filter(
            MatchResultExtraValue.match_result_id == mr.id,
            MatchResultExtraValue.field_key == field_key,
        )
        .first()
    )
    if normalized is None:
        if existing:
            db.delete(existing)
    elif existing:
        existing.field_value = normalized
        existing.source = "manual"
    else:
        db.add(MatchResultExtraValue(
            match_result_id=mr.id,
            field_key=field_key,
            field_value=normalized,
            source="manual",
        ))
    if commit:
        db.commit()
    return {
        "field_key": field.field_key,
        "field_label": field.field_label,
        "value": normalized,
    }
