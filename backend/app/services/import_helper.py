"""
Shared import utilities used by upload.py and all module-specific
headers/confirm endpoints (attr rules, models, URL mappings).
"""
import hashlib
import shutil
import time
import uuid
from pathlib import Path
from typing import Optional

from fastapi import UploadFile
from sqlalchemy.orm import Session


def col_fingerprint(columns: list[str]) -> str:
    """MD5 of sorted column names joined by ','."""
    return hashlib.md5(",".join(sorted(columns)).encode()).hexdigest()


def jaccard(set_a: set, set_b: set) -> float:
    """Jaccard similarity between two sets."""
    if not set_a and not set_b:
        return 1.0
    return len(set_a & set_b) / len(set_a | set_b)


def read_columns(file_path: Path) -> list[str]:
    """Read first-row column names from Excel or CSV (utf-8-sig / gbk fallback)."""
    import pandas as pd
    suffix = file_path.suffix.lower()
    if suffix == ".csv":
        try:
            df = pd.read_csv(file_path, dtype=str, encoding="utf-8-sig", nrows=0)
        except (UnicodeDecodeError, pd.errors.ParserError):
            df = pd.read_csv(file_path, dtype=str, encoding="gbk", nrows=0)
    else:
        df = pd.read_excel(file_path, sheet_name=0, dtype=str, nrows=0)
    return [str(c).strip() for c in df.columns]


def find_best_template(columns: list[str], module: str, db: Session):
    """
    Find best matching ColumnTemplate for the given module.

    Returns (template | None, match_score 0-100).
    Tries exact col_fingerprint match first, then Jaccard similarity.
    """
    from app.models.schemas import ColumnTemplate

    fp = col_fingerprint(columns)
    exact = db.query(ColumnTemplate).filter(
        ColumnTemplate.col_fingerprint == fp,
        ColumnTemplate.module == module,
    ).first()
    if exact:
        return exact, 100

    templates = db.query(ColumnTemplate).filter(
        ColumnTemplate.module == module,
    ).all()
    if not templates:
        return None, 0

    col_set = set(columns)
    best, best_score = None, 0.0
    for tmpl in templates:
        tmpl_cols = set(tmpl.mapping.keys())
        score = jaccard(col_set, tmpl_cols)
        if score > best_score:
            best, best_score = tmpl, score
    return best, round(best_score * 100)


async def save_tmp_file(
    file: UploadFile, upload_dir: str
) -> tuple[str, Path, str]:
    """
    Save uploaded file to <upload_dir>/tmp/{uuid}_{safe_filename}.

    Returns (temp_file_id, path, safe_filename).
    """
    tmp_dir = Path(upload_dir) / "tmp"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    cleanup_old_tmp(tmp_dir)

    temp_file_id = str(uuid.uuid4())
    safe_filename = Path(file.filename).name
    save_path = tmp_dir / f"{temp_file_id}_{safe_filename}"
    with open(save_path, "wb") as f:
        shutil.copyfileobj(file.file, f)
    return temp_file_id, save_path, safe_filename


def cleanup_old_tmp(tmp_dir: Path, max_age_hours: int = 24) -> None:
    """Remove temp files older than max_age_hours (best-effort)."""
    cutoff = time.time() - max_age_hours * 3600
    try:
        for f in tmp_dir.glob("*"):
            if f.is_file() and f.stat().st_mtime < cutoff:
                f.unlink(missing_ok=True)
    except OSError:
        pass
