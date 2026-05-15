#!/usr/bin/env python3
"""
import_model_db.py — 从品类数据库 Excel 批量导入型号库

在阿里云服务器上运行方式：
    # dry-run（只看报告，不写库）
    python scripts/import_model_db.py 耳机数据库.xlsx --category headphone --dry-run

    # 正式入库
    python scripts/import_model_db.py 耳机数据库.xlsx --category headphone
"""
import argparse
import os
import sys

# 将 backend/ 加入 Python 路径，使 app.* 可导入
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

from dotenv import load_dotenv
load_dotenv(os.path.join(os.path.dirname(__file__), "..", "backend", ".env"))

from app.models.database import SessionLocal  # noqa: E402
from app.services.model_db_importer import import_model_db  # noqa: E402


def print_report(stats: dict, dry_run: bool, excel_path: str, category: str) -> None:
    tag = " [DRY-RUN]" if dry_run else ""
    print(f"\n=== 型号库导入报告{tag} ===")
    print(f"文件:              {excel_path}")
    print(f"品类:              {category}")
    print(f"读取总行数:        {stats['total']:>10,}")
    print()
    print("─── 过滤（跳过） ───")
    print(f"  型号脏数据:       {stats['skip_model']:>10,} 行")
    print(f"  品牌脏数据:       {stats['skip_brand']:>10,} 行")
    print(f"  无链接:           {stats['skip_url']:>10,} 行")
    print(f"  无属性:           {stats['skip_no_attr']:>10,} 行")
    print(f"有效行:             {stats['valid_rows']:>10,} 行")
    print(f"去重后唯一型号:     {stats['unique_models']:>10,} 条")
    print()
    print("─── 入库结果 ───")
    if dry_run:
        print("  (dry-run 模式，未写库)")
    else:
        print(f"  models 新增:        {stats['models_new']:>8,} 条")
        print(f"  models 已存在:      {stats['models_existing']:>8,} 条")
        print(f"  model_specs 写入:   {stats['specs_written']:>8,} 条")
        print(f"  url_mappings 新增:  {stats['urls_new']:>8,} 条")
        print(f"  url 提取失败跳过:   {stats['url_extract_fail']:>8,} 条")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="从品类数据库 Excel 批量导入 models / model_specs / item_url_mappings"
    )
    parser.add_argument("excel_path", help="Excel 文件路径（相对或绝对）")
    parser.add_argument(
        "--category", required=True,
        help="品类 code，必须已存在于 categories 表（如 headphone）"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="只统计过滤情况，不执行任何写库操作"
    )
    args = parser.parse_args()

    if not os.path.exists(args.excel_path):
        print(f"错误：文件不存在 — {args.excel_path}", file=sys.stderr)
        sys.exit(1)

    db = SessionLocal()
    try:
        stats = import_model_db(
            excel_path=args.excel_path,
            category_code=args.category,
            db=db,
            dry_run=args.dry_run,
        )
        print_report(stats, args.dry_run, args.excel_path, args.category)
    except ValueError as e:
        print(f"错误：{e}", file=sys.stderr)
        sys.exit(1)
    finally:
        db.close()


if __name__ == "__main__":
    main()
