"""Master-only country and exchange-rate configuration APIs."""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.core.auth_deps import get_current_user, require_admin
from app.models.database import get_db
from app.models.schemas import (
    Country,
    CountryIn,
    CountryOptionOut,
    CountryOut,
    CountryUpdate,
    ExchangeRate,
    ExchangeRateIn,
    ExchangeRateOptionOut,
    ExchangeRateOut,
    ExchangeRateUpdate,
    User,
)
from app.services.currency_service import build_rate_options, list_active_countries

router = APIRouter(prefix="/api", tags=["countries"])

CNY_CODE = "CN"


def _normalize_code(code: str) -> str:
    return code.strip().upper()


@router.get("/countries/options", response_model=list[CountryOptionOut])
def country_options(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Active country options used by the upload page."""
    return [
        {
            "code": country.code,
            "name_cn": country.name_cn,
            "name_en": country.name_en,
            "currency_code": country.currency_code,
            "currency_symbol": country.currency_symbol,
            "region": country.region,
        }
        for country in list_active_countries(db)
    ]


@router.get("/countries", response_model=list[CountryOut])
def list_countries(
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    return (
        db.query(Country)
        .order_by(Country.sort_order, Country.code)
        .all()
    )


@router.post("/countries", response_model=CountryOut, status_code=201)
def create_country(
    payload: CountryIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    code = _normalize_code(payload.code)
    if db.query(Country).filter(Country.code == code).first():
        raise HTTPException(status_code=409, detail="国家码已存在")
    country = Country(
        code=code,
        name_cn=payload.name_cn.strip(),
        name_en=(payload.name_en or "").strip() or None,
        currency_code=payload.currency_code.strip().upper(),
        currency_symbol=(payload.currency_symbol or "").strip() or None,
        region=payload.region,
        is_active=1 if payload.is_active else 0,
        sort_order=payload.sort_order,
    )
    db.add(country)
    db.commit()
    db.refresh(country)
    return country


@router.put("/countries/{code}", response_model=CountryOut)
def update_country(
    code: str,
    payload: CountryUpdate,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    country = db.query(Country).filter(Country.code == _normalize_code(code)).first()
    if not country:
        raise HTTPException(status_code=404, detail="国家不存在")
    if country.code == CNY_CODE:
        if payload.currency_code and payload.currency_code.upper() != "CNY":
            raise HTTPException(status_code=400, detail="中国固定使用 CNY")
        if payload.region and payload.region != "domestic":
            raise HTTPException(status_code=400, detail="中国固定为 domestic")
    if payload.name_cn is not None:
        value = payload.name_cn.strip()
        if not value:
            raise HTTPException(status_code=400, detail="国家名称不能为空")
        country.name_cn = value
    if "name_en" in payload.model_fields_set:
        country.name_en = (payload.name_en or "").strip() or None
    if payload.currency_code is not None:
        country.currency_code = payload.currency_code.strip().upper()
    if "currency_symbol" in payload.model_fields_set:
        country.currency_symbol = (payload.currency_symbol or "").strip() or None
    if payload.region is not None:
        country.region = payload.region
    if payload.is_active is not None:
        if country.code == CNY_CODE and not payload.is_active:
            raise HTTPException(status_code=400, detail="中国不能停用")
        country.is_active = 1 if payload.is_active else 0
    if payload.sort_order is not None:
        country.sort_order = payload.sort_order
    db.commit()
    db.refresh(country)
    return country


@router.delete("/countries/{code}", response_model=CountryOut)
def delete_country(
    code: str,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    country = db.query(Country).filter(Country.code == _normalize_code(code)).first()
    if not country:
        raise HTTPException(status_code=404, detail="国家不存在")
    if country.code == CNY_CODE:
        raise HTTPException(status_code=400, detail="中国不能删除")
    country.is_active = 0
    db.commit()
    db.refresh(country)
    return country


def _rate_out(rate: ExchangeRate, country: Optional[Country] = None) -> dict:
    country = country or None
    return {
        "id": rate.id,
        "country_code": rate.country_code,
        "country_name": country.name_cn if country else None,
        "currency_code": rate.currency_code,
        "currency_symbol": country.currency_symbol if country else None,
        "rate_to_cny": float(rate.rate_to_cny),
        "source": rate.source,
        "operator": rate.operator,
        "remark": rate.remark,
        "updated_at": rate.updated_at.strftime("%Y-%m-%d %H:%M:%S") if rate.updated_at else None,
    }


@router.get("/exchange-rates/options", response_model=list[ExchangeRateOptionOut])
def exchange_rate_options(
    db: Session = Depends(get_db),
    _current_user: User = Depends(get_current_user),
):
    """Read-only display rates for clean detail currency conversion."""
    return build_rate_options(db)


@router.get("/exchange-rates", response_model=list[ExchangeRateOut])
def list_exchange_rates(
    country_code: Optional[str] = None,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    q = db.query(ExchangeRate, Country).outerjoin(Country, Country.code == ExchangeRate.country_code)
    if country_code:
        q = q.filter(ExchangeRate.country_code == _normalize_code(country_code))
    rows = q.order_by(ExchangeRate.country_code).all()
    return [_rate_out(rate, country) for rate, country in rows]


@router.post("/exchange-rates", response_model=ExchangeRateOut, status_code=201)
def create_exchange_rate(
    payload: ExchangeRateIn,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    country_code = _normalize_code(payload.country_code)
    country = db.query(Country).filter(Country.code == country_code).first()
    if not country:
        raise HTTPException(status_code=404, detail="国家不存在")
    if country_code == CNY_CODE:
        raise HTTPException(status_code=400, detail="中国汇率固定为 1，无需配置")
    if db.query(ExchangeRate).filter(ExchangeRate.country_code == country_code).first():
        raise HTTPException(status_code=409, detail="该国家已配置汇率，请直接编辑")
    rate = ExchangeRate(
        country_code=country_code,
        currency_code=country.currency_code,
        rate_to_cny=payload.rate_to_cny,
        source="manual",
        operator=admin.username,
        remark=(payload.remark or "").strip() or None,
    )
    db.add(rate)
    db.commit()
    db.refresh(rate)
    return _rate_out(rate, country)


@router.put("/exchange-rates/{rate_id}", response_model=ExchangeRateOut)
def update_exchange_rate(
    rate_id: int,
    payload: ExchangeRateUpdate,
    db: Session = Depends(get_db),
    admin: User = Depends(require_admin),
):
    rate = db.query(ExchangeRate).filter(ExchangeRate.id == rate_id).first()
    if not rate:
        raise HTTPException(status_code=404, detail="汇率不存在")
    if payload.rate_to_cny is not None:
        if payload.rate_to_cny <= 0:
            raise HTTPException(status_code=400, detail="汇率必须大于 0")
        rate.rate_to_cny = payload.rate_to_cny
    if "remark" in payload.model_fields_set:
        rate.remark = (payload.remark or "").strip() or None
    rate.operator = admin.username
    rate.updated_at = datetime.utcnow()
    db.commit()
    db.refresh(rate)
    country = db.query(Country).filter(Country.code == rate.country_code).first()
    return _rate_out(rate, country)


@router.delete("/exchange-rates/{rate_id}")
def delete_exchange_rate(
    rate_id: int,
    db: Session = Depends(get_db),
    _admin: User = Depends(require_admin),
):
    rate = db.query(ExchangeRate).filter(ExchangeRate.id == rate_id).first()
    if not rate:
        raise HTTPException(status_code=404, detail="汇率不存在")
    db.delete(rate)
    db.commit()
    return {"message": "已删除"}
