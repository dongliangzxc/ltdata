import io

import pandas as pd
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.api.metadata import router
from app.models.database import get_db
from app.models.schemas import Base, Category


def _excel_with_sheet(sheet_name: str) -> bytes:
    buffer = io.BytesIO()
    df = pd.DataFrame([
        {
            "序号": 1,
            "属性字段名称": "品牌",
            "字段类型": "文本型",
            "字段内容实例": "大疆/影石",
            "字段说明": "单选",
        }
    ])
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name=sheet_name, index=False)
    return buffer.getvalue()


def _excel_with_category_code(category_code: str) -> bytes:
    buffer = io.BytesIO()
    df = pd.DataFrame([
        {
            "品类码": category_code,
            "属性字段名称": "形态",
            "字段类型": "文本型",
            "字段内容实例": "一体机/分体机",
            "字段说明": "单选",
        }
    ])
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        df.to_excel(writer, sheet_name="元数据", index=False)
    return buffer.getvalue()


def _client():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    session = Session()
    session.add(Category(code="sports_camera", name="运动相机"))
    session.add(Category(code="vrar", name="智能眼镜"))
    session.commit()

    app = FastAPI()
    app.include_router(router)

    def override_db():
        try:
            yield session
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    return TestClient(app), session, engine


def test_preview_metadata_uses_sheet_name_as_category_code():
    client, session, engine = _client()
    try:
        resp = client.post(
            "/api/metadata/preview",
            files={"file": ("metadata.xlsx", _excel_with_sheet("sports_camera"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        assert resp.status_code == 200
        assert resp.json()["preview"][0]["category_code"] == "sports_camera"
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_preview_metadata_matches_sheet_name_to_category_name():
    client, session, engine = _client()
    try:
        resp = client.post(
            "/api/metadata/preview",
            files={"file": ("metadata.xlsx", _excel_with_sheet("运动相机"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        assert resp.status_code == 200
        assert resp.json()["preview"][0]["category_code"] == "sports_camera"
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_preview_metadata_matches_sheet_name_to_category_code_case_insensitively():
    client, session, engine = _client()
    try:
        resp = client.post(
            "/api/metadata/preview",
            files={"file": ("metadata.xlsx", _excel_with_sheet("VRAR"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        assert resp.status_code == 200
        assert resp.json()["preview"][0]["category_code"] == "vrar"
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_preview_metadata_rejects_unknown_sheet_category():
    client, session, engine = _client()
    try:
        resp = client.post(
            "/api/metadata/preview",
            files={"file": ("metadata.xlsx", _excel_with_sheet("不存在品类"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        assert resp.status_code == 422
        assert "找不到匹配品类" in resp.json()["detail"]
    finally:
        session.close()
        Base.metadata.drop_all(engine)


def test_preview_metadata_canonicalizes_category_code_case():
    client, session, engine = _client()
    try:
        resp = client.post(
            "/api/metadata/preview",
            files={"file": ("metadata.xlsx", _excel_with_category_code("VRAR"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )

        assert resp.status_code == 200
        assert resp.json()["preview"][0]["category_code"] == "vrar"
    finally:
        session.close()
        Base.metadata.drop_all(engine)
