from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from app.core.config import settings
from app.models.database import Base, engine
from app.api import upload, rawdata, clean, export


@asynccontextmanager
async def lifespan(app: FastAPI):
    # 启动时自动建表（开发环境简化用，生产用 alembic）
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title="落土数据处理平台", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    return JSONResponse(
        status_code=500,
        content={"code": 500, "message": str(exc), "data": None},
    )


app.include_router(upload.router)
app.include_router(rawdata.router)
app.include_router(clean.router)
app.include_router(export.router)


@app.get("/health")
def health():
    return {"status": "ok"}
