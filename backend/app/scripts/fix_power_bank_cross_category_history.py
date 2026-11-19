"""修复被错误归到其它品类的移动电源历史记录。

历史库导入早期未按品类隔离型号解析，部分原始品类为「移动电源」的记录
被关联到 smartwatch / kids_smartwatch 的「待补」型号，导致 category_code
也被写成其它品类。本脚本默认 dry-run，只处理：
- 指定月份；
- 原始品类名称/品类码命中目标品类关键词；
- 当前 category_code 不是目标品类；
- 关联型号不是目标品类（或没有型号）。

修复方式：category_code 改为目标品类；若关联型号不属于目标品类则清空 model_id，
并清空由该型号带出的 model_code（保留原始 model_code_raw / model_text）。

用法：
    python -m app.scripts.fix_power_bank_cross_category_history
    python -m app.scripts.fix_power_bank_cross_category_history --apply
"""
from __future__ import annotations

import argparse
import json

from sqlalchemy import or_

from app.models.database import SessionLocal
from app.models.schemas import HistoricalMapping, ModelRecord


def plan_fixes(
    db,
    *,
    target_category: str = "power_bank",
    month: str = "2026-10",
    raw_category_values: tuple[str, ...] = ("移动电源", "充电宝"),
):
    raw_filters = []
    for value in raw_category_values:
        raw_filters.extend([
            HistoricalMapping.category_name_raw == value,
            HistoricalMapping.category_code_raw == value,
        ])
    rows = (
        db.query(HistoricalMapping)
        .filter(
            HistoricalMapping.month == month,
            HistoricalMapping.category_code.isnot(None),
            HistoricalMapping.category_code != target_category,
            or_(*raw_filters),
        )
        .all()
    )
    model_ids = {h.model_id for h in rows if h.model_id}
    models = {
        m.id: m
        for m in db.query(ModelRecord).filter(ModelRecord.id.in_(list(model_ids))).all()
    } if model_ids else {}

    fixes = []
    for history in rows:
        model = models.get(history.model_id)
        keep_model = bool(model and model.category_code == target_category)
        fixes.append({
            "history_id": history.id,
            "platform": history.platform,
            "raw_category_name": history.category_name_raw,
            "raw_category_code": history.category_code_raw,
            "from_category": history.category_code,
            "model_id": history.model_id,
            "model_category": model.category_code if model else None,
            "model_code": history.model_code,
            "model_code_raw": history.model_code_raw,
            "model_text": history.model_text,
            "keep_model_id": keep_model,
            "clear_model_code": not keep_model and not (history.model_code_raw or "").strip(),
        })
    return fixes


def apply_fixes(db, fixes: list[dict], *, target_category: str = "power_bank") -> int:
    if not fixes:
        return 0
    ids = [fix["history_id"] for fix in fixes]
    by_id = {fix["history_id"]: fix for fix in fixes}
    updated = 0
    for start in range(0, len(ids), 1000):
        chunk = ids[start:start + 1000]
        for history in db.query(HistoricalMapping).filter(HistoricalMapping.id.in_(chunk)).all():
            fix = by_id.get(history.id)
            if not fix:
                continue
            history.category_code = target_category
            if not fix["keep_model_id"]:
                history.model_id = None
                if fix["clear_model_code"]:
                    history.model_code = None
            updated += 1
        db.flush()
    db.commit()
    return updated


def main() -> None:
    parser = argparse.ArgumentParser(description="修复移动电源历史记录跨品类错误")
    parser.add_argument("--target-category", default="power_bank")
    parser.add_argument("--month", default="2026-10")
    parser.add_argument("--raw-category", action="append", dest="raw_categories", default=[])
    parser.add_argument("--apply", action="store_true", help="真正写库；默认只输出计划")
    args = parser.parse_args()

    raw_values = tuple(args.raw_categories) or ("移动电源", "充电宝")
    db = SessionLocal()
    try:
        fixes = plan_fixes(
            db,
            target_category=args.target_category,
            month=args.month,
            raw_category_values=raw_values,
        )
        summary = {
            "mode": "apply" if args.apply else "dry-run",
            "target_category": args.target_category,
            "month": args.month,
            "raw_category_values": list(raw_values),
            "candidate_rows": len(fixes),
            "by_from_category": {},
            "keep_model_id": sum(1 for f in fixes if f["keep_model_id"]),
            "clear_model_id": sum(1 for f in fixes if not f["keep_model_id"]),
            "samples": fixes[:10],
        }
        counts: dict[str, int] = {}
        for fix in fixes:
            key = fix["from_category"] or "<空>"
            counts[key] = counts.get(key, 0) + 1
        summary["by_from_category"] = counts
        if args.apply:
            summary["updated"] = apply_fixes(db, fixes, target_category=args.target_category)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    finally:
        db.close()


if __name__ == "__main__":
    main()
