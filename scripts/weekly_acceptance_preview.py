"""Run the built UI and real APIs against fresh, isolated local acceptance data.

Usage: backend/.venv/bin/python scripts/weekly_acceptance_preview.py
No production database, credentials or files are used. Each run gets a new directory.
"""
from pathlib import Path
import argparse
import os
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=8006)
    args = parser.parse_args()
    dist = ROOT / "frontend/dist"
    if not (dist / "index.html").exists():
        parser.error("请先在frontend目录执行npm run build")
    runtime = Path(tempfile.mkdtemp(prefix="luotu-weekly-preview-"))
    os.environ.update(
        DATABASE_URL=f"sqlite:///{runtime / 'main.db'}",
        ANALYTICS_DATABASE_URL=f"sqlite:///{runtime / 'analytics.db'}",
        UPLOAD_DIR=str(runtime / "uploads"), EXPORT_DIR=str(runtime / "exports"),
        CLEAN_BACKGROUND_ENABLED="false", TRANSLATION_ENABLED="false",
        SECRET_KEY="weekly-local-preview-only",
    )
    sys.path.insert(0, str(ROOT / "backend"))
    from passlib.context import CryptContext
    from app.core import security
    # This preview process uses a portable password scheme; production settings stay untouched.
    security.pwd_context = CryptContext(schemes=["pbkdf2_sha256"])
    from app.models.database import Base, engine, SessionLocal
    from app.models.analytics_db import AnalyticsBase, analytics_engine
    from app.models.schemas import User, Category, Country, DispatchRule, ModelRecord, ModelSpec, ItemUrlMapping, MatchRule, BrandRecord, BrandCategory
    from app.main import app
    from app.api import upload
    from fastapi.responses import FileResponse
    import uvicorn

    Base.metadata.create_all(engine)
    AnalyticsBase.metadata.create_all(analytics_engine)
    with SessionLocal() as db:
        db.add(User(username="weekly_qa", hashed_password=security.hash_password("WeeklyTest123!"),
                    name="周度验收", is_admin=1, is_active=1, permissions=[]))
        db.add(Category(code="headphone", name="耳机"))
        db.add(Country(code="CN", name_cn="中国", currency_code="CNY", region="domestic", is_active=1))
        db.add(DispatchRule(category_code="headphone", platform="jd", field="item_name",
                            match_type="contains", value="周度验收", priority=1, is_active=1))
        model = ModelRecord(brand_code="WEEKLYQA", brand_name="测试品牌", model_code="WEEKLY-QA-MODEL",
                            model_name="周度验收型号", category_code="headphone")
        db.add(model); db.flush()
        db.add(ModelSpec(model_id=model.id, spec_name="类型", spec_value="验收耳机"))
        db.add(BrandRecord(brand_code="WEEKLYQA", brand_name="测试品牌"))
        db.add(BrandCategory(brand_code="WEEKLYQA", category_code="headphone"))
        db.add(MatchRule(keyword="周度验收", model_id=model.id, match_type="contains", is_active=1, priority=1))
        for suffix in ("A", "B", "C", "D"):
            db.add(ItemUrlMapping(platform="jd", item_id=f"WEEKLY-ACCEPT-{suffix}", model_id=model.id))
        db.commit()

    def sqlite_progress(db, job, **values):
        # SQLite cannot write progress in a second connection during the import transaction.
        for key, value in values.items():
            if value is not None:
                setattr(job, key, value)
        if values.get("status") == "error":
            db.commit()

    upload._update_upload_job_progress = sqlite_progress

    @app.middleware("http")
    async def preview_ui(request, call_next):
        if request.url.path.startswith("/api/") or request.url.path == "/health":
            return await call_next(request)
        candidate = (dist / request.url.path.lstrip("/")).resolve()
        if candidate.is_relative_to(dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")

    print(f"本地验收地址：http://127.0.0.1:{args.port}/login", flush=True)
    print("账号：weekly_qa；密码：WeeklyTest123!", flush=True)
    print(f"隔离数据目录：{runtime}；重启脚本会创建全新验收数据", flush=True)
    print("本预览使用SQLite和同步清洗，供业务流程验收；MySQL迁移及后台worker需在正式测试环境验证。", flush=True)
    uvicorn.run(app, host="127.0.0.1", port=args.port)


if __name__ == "__main__":
    main()
