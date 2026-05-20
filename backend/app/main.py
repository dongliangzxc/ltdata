from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.core.security import verify_token, hash_password
from app.models.database import Base, engine, SessionLocal
from app.models.analytics_db import AnalyticsBase, analytics_engine
from app.models.schemas import User
from app.api import upload, rawdata, clean, export, metadata, models_api, match_api, publish_api, auth, workbench_api, analytics_api, url_mapping_api
from app.api import rules_api, historical_api, categories_api, correction_rules_api
from app.api.dispatch_api import router as dispatch_router
from app.api.upload_templates_api import router as upload_templates_router


# 不需要鉴权的路径（精确匹配或前缀匹配）
_SKIP_AUTH = {"/api/auth/login", "/health"}
_SKIP_AUTH_PREFIXES = ("/api/export/download/", "/api/workbench/download/", "/api/analytics/download/")


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(bind=engine)
    AnalyticsBase.metadata.create_all(bind=analytics_engine)
    # 若 users 表为空，自动创建默认管理员 admin/luotu123
    db = SessionLocal()
    try:
        if db.query(User).count() == 0:
            db.add(User(username="admin", hashed_password=hash_password("luotu123")))
            db.commit()
    finally:
        db.close()
    yield


app = FastAPI(title="洛图数据处理平台", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    path = request.url.path
    if path in _SKIP_AUTH or path.startswith(_SKIP_AUTH_PREFIXES):
        return await call_next(request)
    token = request.headers.get("Authorization", "").removeprefix("Bearer ").strip()
    if not token or not verify_token(token):
        return JSONResponse(status_code=401, content={"code": 401, "message": "未登录或登录已过期"})
    return await call_next(request)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": str(exc), "data": None},
    )


app.include_router(auth.router)
app.include_router(upload.router)
app.include_router(rawdata.router)
app.include_router(clean.router)
app.include_router(export.router)
app.include_router(metadata.router)
app.include_router(models_api.router)
app.include_router(match_api.router)
app.include_router(publish_api.router)
app.include_router(workbench_api.router)
app.include_router(analytics_api.router)
app.include_router(url_mapping_api.router)
app.include_router(rules_api.router)
app.include_router(historical_api.router)
app.include_router(categories_api.router)
app.include_router(correction_rules_api.router)
app.include_router(dispatch_router)
app.include_router(upload_templates_router)


@app.get("/health")
def health():
    return {"status": "ok"}
