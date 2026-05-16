"""
headphone_data_fixer.py — 修复存量 models 品牌字段 + 补全 metadata_specs 定义。

供 scripts/fix_headphone_data.py 调用，也可单独 import 测试。
"""
from sqlalchemy.orm import Session

from app.models.schemas import ModelRecord, MetadataSpec
from app.services.model_db_importer import parse_brand, ATTR_SPEC_TYPES, _DECIMAL_PLACES


_COMMIT_BATCH = 500


def fix_brands(db: Session) -> dict:
    """
    遍历所有 models，修复 brand_code/brand_name。

    Returns:
        stats dict — brand_fixed（brand_code 被拆分数），
                     brand_name_filled（brand_name 从空填充数），
                     skipped（无需修改数）
    """
    stats = {"brand_fixed": 0, "brand_name_filled": 0, "skipped": 0}
    pending = 0

    for rec in db.query(ModelRecord).all():
        new_code, new_name = parse_brand(rec.brand_code)
        code_changed = rec.brand_code != new_code
        name_changed = rec.brand_name != new_name

        if not code_changed and not name_changed:
            stats["skipped"] += 1
            continue

        if code_changed:
            rec.brand_code = new_code
            stats["brand_fixed"] += 1

        if name_changed:
            rec.brand_name = new_name
            if not code_changed:
                stats["brand_name_filled"] += 1

        pending += 1
        if pending >= _COMMIT_BATCH:
            db.commit()
            pending = 0

    if pending:
        db.commit()
    return stats


def seed_metadata_specs(db: Session, category_code: str) -> int:
    """
    为品类补全 metadata_specs 定义（已存在则跳过，幂等）。

    Returns:
        新插入的条目数
    """
    existing = {
        s.spec_name
        for s in db.query(MetadataSpec).filter_by(category_code=category_code).all()
    }
    inserted = 0
    for spec_name, spec_type in ATTR_SPEC_TYPES.items():
        if spec_name in existing:
            continue
        db.add(MetadataSpec(
            category_code=category_code,
            spec_name=spec_name,
            spec_type=spec_type,
            required=0,
            single_select=1,
            decimal_places=_DECIMAL_PLACES.get(spec_name),
        ))
        inserted += 1
    db.commit()
    return inserted
