#!/usr/bin/env python3
"""
sync_metadata_spec_values.py — 从 model_specs 归纳 distinct 值，填充 metadata_specs.spec_values

在项目根目录运行：
    python scripts/sync_metadata_spec_values.py --dry-run               # 预览，不写库
    python scripts/sync_metadata_spec_values.py --category headphone    # 指定品类
    python scripts/sync_metadata_spec_values.py                         # 处理所有品类
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from app.models.database import SessionLocal                          # noqa: E402
from app.services.metadata_spec_syncer import sync_spec_values        # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从 model_specs 归纳 distinct 值，填充 metadata_specs.spec_values"
    )
    parser.add_argument("--category", default=None, help="指定品类 code（留空处理所有品类）")
    parser.add_argument("--dry-run", action="store_true", help="只预览，不写库")
    args = parser.parse_args()

    if args.dry_run:
        from collections import defaultdict
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from app.core.config import settings
        from app.models.schemas import MetadataSpec, ModelRecord, ModelSpec

        engine = create_engine(settings.DATABASE_URL)
        Session = sessionmaker(bind=engine)
        db = Session()
        try:
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
            if args.category:
                q = q.filter(ModelRecord.category_code == args.category)

            counts: dict[tuple[str, str], dict[str, int]] = defaultdict(lambda: defaultdict(int))
            for cat, sname, sval in q.yield_per(1000):
                counts[(cat, sname)][sval] += 1

            meta_q = db.query(MetadataSpec)
            if args.category:
                meta_q = meta_q.filter(MetadataSpec.category_code == args.category)
            meta_records = {
                (m.category_code, m.spec_name): m
                for m in meta_q.all()
            }

            label = f"category={args.category}" if args.category else "所有品类"
            print(f"=== DRY-RUN（不写库）=== {label}")
            pending = 0
            for (cat, sname), val_counts in sorted(counts.items()):
                if (cat, sname) not in meta_records:
                    continue
                ordered = sorted(val_counts.items(), key=lambda x: (-x[1], x[0]))
                new_values = ",".join(v for v, _ in ordered)
                preview = new_values if len(new_values) <= 60 else new_values[:57] + "..."
                print(f"  [{cat}] {sname:<25} →  {preview}")
                pending += 1
            print(f"\n  共 {pending} 条待更新")
        finally:
            db.close()
        return

    db = SessionLocal()
    try:
        stats = sync_spec_values(db, args.category)
        label = args.category if args.category else "所有品类"
        print(f"=== 同步报告 === {label}")
        print(f"  updated: {stats['updated']:>6,}")
        print(f"  skipped: {stats['skipped']:>6,}")
    finally:
        db.close()


if __name__ == "__main__":
    main()
