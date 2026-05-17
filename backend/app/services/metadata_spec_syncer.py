"""
metadata_spec_syncer.py — 从 model_specs 归纳 distinct 值，填充 metadata_specs.spec_values。

供 scripts/sync_metadata_spec_values.py 调用，也可单独 import 测试。
"""
from collections import defaultdict

from sqlalchemy.orm import Session

from app.models.schemas import MetadataSpec, ModelRecord, ModelSpec


def sync_spec_values(db: Session, category_code: str | None = None) -> dict:
    """
    对每个 (category_code, spec_name)，从 model_specs 收集 distinct 非空值（按出现次数降序），
    拼成逗号字符串写入 metadata_specs.spec_values。

    Args:
        category_code: 指定品类（如 "headphone"）；None 表示处理所有品类。

    Returns:
        {"updated": N, "skipped": N}
    """
    # ── 1. 查 model_specs，按 (category_code, spec_name, spec_value) 统计出现次数 ──
    q = (
        db.query(
            ModelRecord.category_code,
            ModelSpec.spec_name,
            ModelSpec.spec_value,
        )
        .join(ModelRecord, ModelSpec.model_id == ModelRecord.id)
        .filter(
            ModelSpec.spec_value.isnot(None),
            ModelSpec.spec_value != "",
        )
    )
    if category_code is not None:
        q = q.filter(ModelRecord.category_code == category_code)

    # { (cat_code, spec_name): {spec_value: count} }
    counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for cat, sname, sval in q.yield_per(1000):
        counts[(cat, sname)][sval] += 1

    # ── 2. 查 metadata_specs（确定哪些 (cat, spec_name) 有定义）──────────────────
    meta_q = db.query(MetadataSpec)
    if category_code is not None:
        meta_q = meta_q.filter(MetadataSpec.category_code == category_code)
    meta_records = {
        (m.category_code, m.spec_name): m
        for m in meta_q.all()
    }

    # ── 3. 对比并更新 ─────────────────────────────────────────────────────────────
    stats = {"updated": 0, "skipped": 0}
    for (cat, sname), val_counts in counts.items():
        meta = meta_records.get((cat, sname))
        if meta is None:
            continue

        ordered = sorted(val_counts.items(), key=lambda x: (-x[1], x[0]))
        new_values = ",".join(v for v, _ in ordered)

        if meta.spec_values == new_values:
            stats["skipped"] += 1
        else:
            meta.spec_values = new_values
            stats["updated"] += 1

    if stats["updated"]:
        db.commit()
    return stats
