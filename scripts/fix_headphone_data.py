#!/usr/bin/env python3
"""
fix_headphone_data.py — 修复存量 models 品牌字段 + 补全 headphone metadata_specs

在项目根目录运行：
    python scripts/fix_headphone_data.py --dry-run   # 只看报告，不写库
    python scripts/fix_headphone_data.py              # 正式执行
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from app.models.database import SessionLocal  # noqa: E402
from app.services.headphone_data_fixer import fix_brands, seed_metadata_specs  # noqa: E402
from app.services.model_db_importer import ATTR_SPEC_TYPES  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="修复 models 品牌字段 + 补全 headphone metadata_specs"
    )
    parser.add_argument("--dry-run", action="store_true", help="只统计现状，不写库")
    args = parser.parse_args()

    if args.dry_run:
        from sqlalchemy import create_engine, text
        from app.core.config import settings
        engine = create_engine(settings.DATABASE_URL)
        with engine.connect() as conn:
            slash_count = conn.execute(
                text("SELECT COUNT(*) FROM models WHERE brand_code LIKE '%/%'")
            ).scalar()
            no_name = conn.execute(
                text("SELECT COUNT(*) FROM models WHERE brand_name IS NULL OR brand_name = ''")
            ).scalar()
            meta_count = conn.execute(
                text("SELECT COUNT(*) FROM metadata_specs WHERE category_code='headphone'")
            ).scalar()
        print("=== DRY-RUN（不写库） ===")
        print(f"  brand_code 含斜杠（待拆分）:    {slash_count:>8,}")
        print(f"  brand_name 为空（待填充）:       {no_name:>8,}")
        print(f"  headphone metadata_specs 现有:   {meta_count:>8}")
        print(f"  headphone metadata_specs 待补:   {max(0, len(ATTR_SPEC_TYPES) - meta_count):>8}")
        return

    db = SessionLocal()
    try:
        brand_stats = fix_brands(db)
        meta_inserted = seed_metadata_specs(db, "headphone")
        print("=== 修复报告 ===")
        print(f"  brand_code 拆分修复: {brand_stats['brand_fixed']:>8,}")
        print(f"  brand_name 填充:     {brand_stats['brand_name_filled']:>8,}")
        print(f"  无需修改（跳过）:    {brand_stats['skipped']:>8,}")
        print(f"  metadata_specs 新增: {meta_inserted:>8,}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
