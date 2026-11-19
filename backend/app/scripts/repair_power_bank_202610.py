"""移动电源 2026-10 历史库型号回填 + 待处理行重匹配。

背景：线下清洗后更新历史库/映射/产品属性，平台已有任务不会自动重跑；
并且历史库早期导入存在跨品类型号关联。本脚本只处理指定品类/月份：

1. 仅对 category_code 属于目标品类或为空的历史记录，按「品牌 + 型号码/型号名」
   唯一匹配当前品类下的有效型号，回填 ``historical_mappings.model_id``；
2. 对指定清洗任务中仍为 pending / text_only 且未发布的匹配结果，按回填后的
   历史库重新执行匹配；
3. 不修改 confirmed / ignored / excluded 以及已发布记录。

默认 dry-run，只输出统计；加 ``--apply`` 才写库。

用法：
    python -m app.scripts.repair_power_bank_202610 --job-id 390 --job-id 385
    python -m app.scripts.repair_power_bank_202610 --job-id 390 --apply
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from typing import Iterable

from sqlalchemy import or_

from app.api.historical_api import (
    _effective_brand_code,
    _is_unknown_brand,
    _usable_identity_value,
)
from app.models.analytics_db import AnalyticsSession, PublishedItem
from app.models.database import SessionLocal
from app.models.schemas import (
    CleanJobRecord,
    HistoricalMapping,
    MatchResult,
    ModelRecord,
)
from app.services.matcher import (
    _is_generic_brand_code,
    _is_pending_placeholder_model,
    run_match,
)


def _model_indexes(db, category_code: str):
    models = (
        db.query(ModelRecord)
        .filter(ModelRecord.category_code == category_code)
        .all()
    )
    valid = [
        model for model in models
        if (
            (model.status or "active") == "active"
            and not _is_generic_brand_code(model.brand_code)
            and not _is_pending_placeholder_model(model)
        )
    ]
    by_code: dict[tuple[str, str], list[ModelRecord]] = defaultdict(list)
    by_name: dict[tuple[str, str], list[ModelRecord]] = defaultdict(list)
    for model in valid:
        brand = (model.brand_code or "").strip()
        if model.model_code:
            by_code[(brand, model.model_code.strip())].append(model)
        if model.model_name:
            by_name[(brand, model.model_name.strip())].append(model)
    return valid, by_code, by_name


_PENDING_IDENTITY_VALUES = {"待补", "待补型号"}


def _is_pending_identity_value(value: str | None) -> bool:
    return (value or "").strip().upper() in _PENDING_IDENTITY_VALUES


def _brand_level_empty_models(valid_models: list[ModelRecord]) -> dict[str, ModelRecord]:
    """品牌+品类下只有一条 active 型号且型号码为空时，可作为该品牌的无型号兜底。

    若该品牌还有其它真实型号，则不猜，避免把不同商品都归到同一条空型号。
    """
    grouped: dict[str, list[ModelRecord]] = defaultdict(list)
    for model in valid_models:
        grouped[(model.brand_code or "").strip()].append(model)
    return {
        brand: models[0]
        for brand, models in grouped.items()
        if len(models) == 1 and not (models[0].model_code or "").strip()
    }


def _resolve_history_model(history: HistoricalMapping, by_code, by_name) -> tuple[ModelRecord | None, str]:
    brand = _effective_brand_code(history.brand_code_raw, history.brand_raw)
    if _is_unknown_brand(brand):
        return None, "missing_brand"
    model_code = _usable_identity_value(history.model_code_raw) or _usable_identity_value(history.model_code)
    model_name = _usable_identity_value(history.model_text)
    if _is_pending_identity_value(model_code):
        model_code = None
    if _is_pending_identity_value(model_name):
        model_name = None
    key = model_code or model_name
    if not key:
        return None, "missing_model_identity"

    candidates = list(by_code.get(((brand or "").strip(), key), []))
    if not candidates and not model_code and model_name:
        candidates = list(by_name.get(((brand or "").strip(), model_name), []))
    if not candidates:
        return None, "model_not_in_current_library"
    if len(candidates) > 1:
        return None, "ambiguous_model"
    return candidates[0], "unique_exact"


def plan_history_links(db, *, category_code: str, month: str, limit: int | None = None):
    valid_models, by_code, by_name = _model_indexes(db, category_code)
    valid_ids = {model.id for model in valid_models}
    brand_level_models = _brand_level_empty_models(valid_models)
    rows = (
        db.query(HistoricalMapping)
        .filter(
            HistoricalMapping.month == month,
            or_(
                HistoricalMapping.category_code == category_code,
                HistoricalMapping.category_code.is_(None),
            ),
        )
        .all()
    )
    links: dict[int, int] = {}
    reasons = Counter()
    candidates = 0
    for history in rows:
        candidates += 1
        if history.model_id in valid_ids:
            reasons["already_linked"] += 1
            continue
        model, reason = _resolve_history_model(history, by_code, by_name)
        if model is None and reason == "missing_model_identity":
            brand = (_effective_brand_code(history.brand_code_raw, history.brand_raw) or "").strip()
            fallback = brand_level_models.get(brand)
            if fallback is not None:
                model = fallback
                reason = "brand_level_empty_model"
        reasons[reason] += 1
        if model is None:
            continue
        links[history.id] = model.id
        if limit is not None and len(links) >= limit:
            break
    return {
        "rows_scanned": candidates,
        "links": links,
        "reasons": dict(reasons),
        "distinct_models": len(set(links.values())),
    }


def apply_history_links(db, links: dict[int, int]) -> int:
    if not links:
        return 0
    ids = list(links)
    updated = 0
    for start in range(0, len(ids), 1000):
        chunk = ids[start:start + 1000]
        for history in db.query(HistoricalMapping).filter(HistoricalMapping.id.in_(chunk)).all():
            model_id = links.get(history.id)
            if model_id is None:
                continue
            history.model_id = model_id
            updated += 1
        db.flush()
    db.commit()
    return updated


def _published_match_result_ids(clean_job_ids: Iterable[int]) -> set[int]:
    job_ids = list(clean_job_ids)
    if not job_ids:
        return set()
    analytics = AnalyticsSession()
    try:
        return {
            match_result_id
            for (match_result_id,) in analytics.query(PublishedItem.match_result_id)
            .filter(PublishedItem.clean_job_id.in_(job_ids))
            .all()
            if match_result_id is not None
        }
    finally:
        analytics.close()


def plan_rebuild(db, clean_job_ids: Iterable[int], published_ids: set[int]):
    job_ids = list(clean_job_ids)
    if not job_ids:
        return {}
    rows = (
        db.query(MatchResult.id, MatchResult.raw_data_id, MatchResult.clean_job_id)
        .filter(
            MatchResult.clean_job_id.in_(job_ids),
            MatchResult.match_status.in_(["pending", "text_only"]),
            MatchResult.is_disabled == 0,
        )
        .all()
    )
    plan: dict[int, list[int]] = defaultdict(list)
    skipped_published = 0
    for match_id, raw_data_id, clean_job_id in rows:
        if match_id in published_ids:
            skipped_published += 1
            continue
        plan[clean_job_id].append(raw_data_id)
    return {
        "by_job": dict(plan),
        "rows": sum(len(ids) for ids in plan.values()),
        "skipped_published": skipped_published,
    }


def _status_counts(db, clean_job_ids: Iterable[int]) -> dict:
    rows = (
        db.query(MatchResult.clean_job_id, MatchResult.match_status)
        .filter(MatchResult.clean_job_id.in_(list(clean_job_ids)))
        .all()
    )
    counts = Counter(f"{job}:{status}" for job, status in rows)
    return dict(counts)


def main() -> None:
    parser = argparse.ArgumentParser(description="移动电源 2026-10 历史库型号回填与重匹配")
    parser.add_argument("--category", default="power_bank")
    parser.add_argument("--month", default="2026-10")
    parser.add_argument("--job-id", action="append", type=int, dest="job_ids", default=[])
    parser.add_argument("--limit", type=int, default=None, help="dry-run 时最多展示/回填条数")
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只输出计划")
    parser.add_argument("--skip-rebuild", action="store_true", help="只回填历史库，不重匹配")
    args = parser.parse_args()
    if args.apply and args.limit is not None:
        raise SystemExit("--limit 仅用于 dry-run 预览，不能与 --apply 同时使用")

    db = SessionLocal()
    try:
        job_ids = list(args.job_ids)
        if not job_ids:
            job_ids = [
                job_id
                for (job_id,) in (
                    db.query(CleanJobRecord.id)
                    .filter(CleanJobRecord.category_code == args.category)
                    .all()
                )
            ]
        if not job_ids:
            raise SystemExit("未指定 --job-id，且没有找到该品类的清洗任务")
        if not db.query(CleanJobRecord.id).filter(CleanJobRecord.id.in_(job_ids)).count():
            raise SystemExit("指定清洗任务不存在")

        before = _status_counts(db, job_ids)
        history_plan = plan_history_links(db, category_code=args.category, month=args.month, limit=args.limit)
        published_ids = _published_match_result_ids(job_ids)
        rebuild_plan = (
            {"by_job": {}, "rows": 0, "skipped_published": 0}
            if args.skip_rebuild
            else plan_rebuild(db, job_ids, published_ids)
        )

        summary = {
            "mode": "apply" if args.apply else "dry-run",
            "category": args.category,
            "month": args.month,
            "job_ids": job_ids,
            "history": {
                "rows_scanned": history_plan["rows_scanned"],
                "linkable": len(history_plan["links"]),
                "distinct_models": history_plan["distinct_models"],
                "reasons": history_plan["reasons"],
            },
            "rebuild": {
                "jobs": {str(job): len(ids) for job, ids in rebuild_plan["by_job"].items()},
                "rows": rebuild_plan["rows"],
                "skipped_published": rebuild_plan["skipped_published"],
            },
            "status_before": before,
        }

        if args.apply:
            updated = apply_history_links(db, history_plan["links"])
            rematch_results = {}
            for job_id, raw_ids in rebuild_plan["by_job"].items():
                if not raw_ids:
                    continue
                rematch_results[str(job_id)] = run_match(db, job_id, raw_data_ids=raw_ids)
            summary["history"]["updated"] = updated
            summary["rematch"] = rematch_results
            summary["status_after"] = _status_counts(db, job_ids)

        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
