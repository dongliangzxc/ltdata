#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.models.database import SessionLocal
from app.services.legacy_historical_metadata import import_legacy_historical_metadata

DEFAULT_FILES = [
    ROOT / "平台元数据" / "历史库" / "【202601】洛图科技笔记本电脑线上数据库.xlsx",
    ROOT / "平台元数据" / "历史库" / "路由器数据库202501-202604.xlsx",
    ROOT / "平台元数据" / "历史库" / "2023-2026.04门锁-传统+新兴.xlsx",
]


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize metadata/model specs from legacy historical Excel files.")
    parser.add_argument("--apply", action="store_true", help="Write changes to the database. Without this flag the script runs dry-run only.")
    parser.add_argument("files", nargs="*", type=Path, help="Excel files to import. Defaults to the three files under 平台元数据/历史库.")
    args = parser.parse_args()

    files = args.files or DEFAULT_FILES
    missing = [str(path) for path in files if not path.exists()]
    if missing:
        print(json.dumps({"error": "missing_files", "files": missing}, ensure_ascii=False, indent=2))
        return 2

    db = SessionLocal()
    try:
        report = import_legacy_historical_metadata(db, files, dry_run=not args.apply)
        print(json.dumps(report, ensure_ascii=False, indent=2))
    finally:
        db.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
