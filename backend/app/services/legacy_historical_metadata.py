from __future__ import annotations

from collections import Counter, defaultdict
from pathlib import Path
from typing import Iterable

import pandas as pd
from sqlalchemy.orm import Session

from app.api.historical_api import (
    HISTORICAL_FIELD_ALIASES,
    _clean_value,
    _detect_sheet_and_mapping,
    _infer_category_code,
    _is_unknown_brand,
    _read_sheet_preview,
)
from app.models.schemas import MetadataSpec, ModelRecord, ModelSpec

EXTRA_NON_ATTRIBUTE_COLUMNS = {"半年度", "季度", "价格段", "店铺名称", "宝贝链接品牌"}
SPEC_VALUES_MAX_LENGTH = 60000
SPEC_VALUES_MAX_OPTIONS = 500
CORE_COLUMNS = {
    alias
    for aliases in HISTORICAL_FIELD_ALIASES.values()
    for alias in aliases
} | EXTRA_NON_ATTRIBUTE_COLUMNS
MODEL_COLUMN_CANDIDATES = {
    "brand": ("品牌", "品牌名称", "brand"),
    "brand_code": ("品牌码", "品牌编码", "brand_code"),
    "model": ("产品系列", "型号", "机型", "系列", "model", "model_code"),
    "model_code": ("型号码", "型号编码"),
}


def import_legacy_historical_metadata(
    db: Session,
    paths: Iterable[str | Path],
    *,
    dry_run: bool = True,
) -> dict:
    report = {
        "dry_run": dry_run,
        "totals": {"metadata_specs": 0, "models": 0, "model_specs": 0, "conflicts": 0},
        "files": [],
    }

    for path_value in paths:
        path = Path(path_value)
        file_report = _empty_file_report(path)
        report["files"].append(file_report)

        category_code = _infer_category_code(path.name, db)
        file_report["category_code"] = category_code
        if not category_code:
            file_report["error"] = "无法从文件名识别品类"
            continue

        try:
            xls = pd.ExcelFile(path)
            sheet_name, columns, mapping = _detect_sheet_and_mapping(xls)
            df = _read_sheet_preview(xls, sheet_name)
        except Exception as exc:  # pragma: no cover - defensive reporting for batch imports
            file_report["error"] = str(exc)
            continue

        file_report["sheet_name"] = sheet_name
        property_columns = _property_columns(columns)
        file_report["metadata_specs"] = len(property_columns)

        brand_col = mapping.get("brand_raw") or _find_column(columns, MODEL_COLUMN_CANDIDATES["brand"])
        brand_code_col = mapping.get("brand_code_raw") or _find_column(columns, MODEL_COLUMN_CANDIDATES["brand_code"])
        model_col = mapping.get("model_text") or _find_column(columns, MODEL_COLUMN_CANDIDATES["model"])
        model_code_col = mapping.get("model_code_raw") or _find_column(columns, MODEL_COLUMN_CANDIDATES["model_code"])

        model_values: dict[tuple[str, str, str], dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))
        spec_value_counts: dict[str, Counter] = defaultdict(Counter)
        model_names: dict[tuple[str, str, str], str] = {}
        brand_names: dict[tuple[str, str, str], str] = {}

        for _, raw_row in df.iterrows():
            row = raw_row.to_dict()
            brand_raw = _clean_value(row.get(brand_col)) if brand_col else None
            brand_code_raw = _clean_value(row.get(brand_code_col)) if brand_code_col else None
            model_text = _clean_value(row.get(model_col)) if model_col else None
            model_code_raw = _clean_value(row.get(model_code_col)) if model_code_col else None
            identity = _model_identity(
                brand_raw=brand_raw,
                brand_code_raw=brand_code_raw,
                model_text=model_text,
                model_code_raw=model_code_raw,
                category_code=category_code,
            )
            if identity is None:
                continue
            key = (identity["brand_code"], identity["model_code"], category_code)
            model_names[key] = identity["model_name"]
            brand_names[key] = identity["brand_name"]
            for spec_name in property_columns:
                value = _clean_value(row.get(spec_name))
                if value is not None:
                    model_values[key][spec_name].append(value)
                    spec_value_counts[spec_name][value] += 1

        resolved_specs, conflicts = _resolve_model_specs(model_values)
        file_report["conflicts"] = conflicts
        file_report["models"] = len(resolved_specs)
        file_report["model_specs"] = sum(len(specs) for specs in resolved_specs.values())
        conflicted_model_keys = _apply_read_only_model_conflict_analysis(db, file_report, resolved_specs)

        if dry_run:
            _add_file_totals(report, file_report)
            continue

        try:
            for spec_name in property_columns:
                _upsert_metadata_spec(db, category_code, spec_name, spec_value_counts.get(spec_name))
            for key, specs in resolved_specs.items():
                if key in conflicted_model_keys:
                    continue
                brand_code, model_code, key_category_code = key
                model, conflict = _upsert_model(
                    db,
                    brand_code=brand_code,
                    model_code=model_code,
                    category_code=key_category_code,
                    brand_name=brand_names.get(key),
                    model_name=model_names.get(key),
                )
                if conflict:
                    file_report["conflicts"].append(conflict)
                    file_report["models"] -= 1
                    file_report["model_specs"] -= len(specs)
                    continue
                for spec_name, spec_value in specs.items():
                    _upsert_model_spec(db, model.id, spec_name, spec_value)
            db.commit()
        except Exception as exc:
            db.rollback()
            file_report["error"] = str(exc)
            continue

        _add_file_totals(report, file_report)

    return report


def _empty_file_report(path: Path) -> dict:
    return {
        "file": str(path),
        "sheet_name": None,
        "category_code": None,
        "metadata_specs": 0,
        "models": 0,
        "model_specs": 0,
        "conflicts": [],
    }


def _add_file_totals(report: dict, file_report: dict) -> None:
    report["totals"]["metadata_specs"] += file_report["metadata_specs"]
    report["totals"]["models"] += file_report["models"]
    report["totals"]["model_specs"] += file_report["model_specs"]
    report["totals"]["conflicts"] += len(file_report["conflicts"])


def _apply_read_only_model_conflict_analysis(db: Session, file_report: dict, resolved_specs: dict) -> set[tuple[str, str, str]]:
    conflicted_keys = set()
    for key, specs in resolved_specs.items():
        brand_code, model_code, category_code = key
        model = db.query(ModelRecord).filter_by(brand_code=brand_code, model_code=model_code).first()
        if not model or not model.category_code or model.category_code == category_code:
            continue
        file_report["conflicts"].append(_model_category_conflict(
            brand_code=brand_code,
            model_code=model_code,
            existing_category_code=model.category_code,
            import_category_code=category_code,
        ))
        file_report["models"] -= 1
        file_report["model_specs"] -= len(specs)
        conflicted_keys.add(key)
    return conflicted_keys


def _property_columns(columns: list[str]) -> list[str]:
    excluded = set(CORE_COLUMNS)
    for aliases in MODEL_COLUMN_CANDIDATES.values():
        excluded.update(aliases)
    return [
        column
        for column in columns
        if column and not str(column).strip().startswith("Unnamed") and column not in excluded
    ]


def _find_column(columns: list[str], candidates: tuple[str, ...]) -> str | None:
    for candidate in candidates:
        if candidate in columns:
            return candidate
    return None


def _model_identity(
    *,
    brand_raw: str | None,
    brand_code_raw: str | None,
    model_text: str | None,
    model_code_raw: str | None,
    category_code: str,
) -> dict | None:
    model_code = model_code_raw or model_text
    model_name = model_text or model_code_raw
    if not model_code or not model_name:
        return None
    brand_code = brand_code_raw if not _is_unknown_brand(brand_code_raw) else brand_raw
    if _is_unknown_brand(brand_code):
        return None
    brand_name = brand_raw if not _is_unknown_brand(brand_raw) else brand_code
    return {
        "brand_code": brand_code,
        "brand_name": brand_name,
        "model_code": model_code,
        "model_name": model_name,
        "category_code": category_code,
    }


def _resolve_model_specs(model_values: dict[tuple[str, str, str], dict[str, list[str]]]) -> tuple[dict, list[dict]]:
    resolved = {}
    conflicts = []
    for key, specs in model_values.items():
        brand_code, model_code, category_code = key
        resolved[key] = {}
        for spec_name, values in specs.items():
            counter = Counter(values)
            selected_value = _choose_value(values, counter)
            if len(counter) > 1:
                conflicts.append({
                    "type": "spec_value_conflict",
                    "brand_code": brand_code,
                    "model_code": model_code,
                    "category_code": category_code,
                    "spec_name": spec_name,
                    "counts": dict(counter),
                    "selected_value": selected_value,
                    "resolution": "most_frequent_latest_tie",
                })
            resolved[key][spec_name] = selected_value
    return resolved, conflicts


def _choose_value(values: list[str], counter: Counter) -> str:
    max_count = max(counter.values())
    tied = {value for value, count in counter.items() if count == max_count}
    for value in reversed(values):
        if value in tied:
            return value
    return values[-1]


def _upsert_metadata_spec(db: Session, category_code: str, spec_name: str, value_counts: Counter | None = None) -> MetadataSpec:
    spec = db.query(MetadataSpec).filter_by(category_code=category_code, spec_name=spec_name).first()
    if spec is None:
        spec = MetadataSpec(
            category_code=category_code,
            spec_name=spec_name,
            spec_type="文本型",
            required=0,
            single_select=1,
        )
        db.add(spec)
    else:
        spec.spec_type = spec.spec_type or "文本型"
    if value_counts:
        merged_values = _ordered_spec_values(value_counts, spec.spec_values)
        if merged_values is not None:
            spec.spec_values = merged_values
    return spec


def _ordered_spec_values(value_counts: Counter, existing_values: str | None = None) -> str | None:
    existing = [value.strip() for value in (existing_values or "").split(",") if value.strip()]
    if len(set(existing) | set(value_counts)) > SPEC_VALUES_MAX_OPTIONS:
        return existing_values

    values = []
    seen = set()
    total_length = 0
    for value in existing:
        if value in seen:
            continue
        next_length = total_length + len(value) + (1 if values else 0)
        if next_length > SPEC_VALUES_MAX_LENGTH:
            return existing_values
        values.append(value)
        seen.add(value)
        total_length = next_length

    for value, _ in sorted(value_counts.items(), key=lambda item: (-item[1], item[0])):
        if value in seen:
            continue
        next_length = total_length + len(value) + (1 if values else 0)
        if next_length > SPEC_VALUES_MAX_LENGTH:
            return existing_values
        values.append(value)
        seen.add(value)
        total_length = next_length
    return ",".join(values) if values else None


def _upsert_model(
    db: Session,
    *,
    brand_code: str,
    model_code: str,
    category_code: str,
    brand_name: str | None,
    model_name: str | None,
) -> tuple[ModelRecord | None, dict | None]:
    model = db.query(ModelRecord).filter_by(brand_code=brand_code, model_code=model_code).first()
    if model is None:
        model = ModelRecord(
            brand_code=brand_code,
            model_code=model_code,
            category_code=category_code,
            brand_name=brand_name,
            model_name=model_name,
        )
        db.add(model)
        db.flush()
        return model, None
    if model.category_code and model.category_code != category_code:
        return None, _model_category_conflict(
            brand_code=brand_code,
            model_code=model_code,
            existing_category_code=model.category_code,
            import_category_code=category_code,
        )
    if not model.category_code:
        model.category_code = category_code
    model.brand_name = brand_name or model.brand_name
    model.model_name = model_name or model.model_name
    return model, None


def _model_category_conflict(
    *,
    brand_code: str,
    model_code: str,
    existing_category_code: str,
    import_category_code: str,
) -> dict:
    return {
        "type": "model_category_conflict",
        "brand_code": brand_code,
        "model_code": model_code,
        "existing_category_code": existing_category_code,
        "import_category_code": import_category_code,
    }


def _upsert_model_spec(db: Session, model_id: int, spec_name: str, spec_value: str) -> ModelSpec:
    spec = db.query(ModelSpec).filter_by(model_id=model_id, spec_name=spec_name).first()
    if spec is None:
        spec = ModelSpec(model_id=model_id, spec_name=spec_name, spec_value=spec_value)
        db.add(spec)
    else:
        spec.spec_value = spec_value
    return spec
