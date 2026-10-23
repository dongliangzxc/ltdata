"""Country and exchange-rate helpers shared by upload, clean and match APIs."""
from __future__ import annotations

from typing import Any, Optional

from sqlalchemy.orm import Session

from app.models.schemas import Country, ExchangeRate

CNY_COUNTRY_CODE = "CN"
CNY_CURRENCY_CODE = "CNY"


def get_country(db: Session, country_code: str | None) -> Country | None:
    if not country_code:
        return None
    return db.query(Country).filter(Country.code == country_code).first()


def list_active_countries(db: Session) -> list[Country]:
    return (
        db.query(Country)
        .filter(Country.is_active == 1)
        .order_by(Country.sort_order, Country.code)
        .all()
    )


def build_rate_map(db: Session) -> dict[str, dict[str, Any]]:
    """Return {country_code: {currency_code, rate_to_cny}} for active countries.

    CN is always available with a rate of 1.  Countries without a configured
    rate are omitted, so callers can render an explicit "未配置汇率" state.
    """
    rates: dict[str, dict[str, Any]] = {
        CNY_COUNTRY_CODE: {
            "currency_code": CNY_CURRENCY_CODE,
            "rate_to_cny": 1.0,
        }
    }
    rows = (
        db.query(ExchangeRate, Country)
        .join(Country, Country.code == ExchangeRate.country_code)
        .filter(Country.is_active == 1)
        .all()
    )
    for rate, country in rows:
        rates[country.code] = {
            "currency_code": rate.currency_code or country.currency_code,
            "rate_to_cny": float(rate.rate_to_cny),
        }
    return rates


def build_rate_options(db: Session) -> list[dict[str, Any]]:
    """Return display-currency options, including CN/CNY at rate 1."""
    countries = list_active_countries(db)
    rate_rows = {
        rate.country_code: rate
        for rate in db.query(ExchangeRate).all()
    }
    options: list[dict[str, Any]] = []
    for country in countries:
        if country.code == CNY_COUNTRY_CODE:
            rate = 1.0
        else:
            configured = rate_rows.get(country.code)
            if configured is None:
                continue
            rate = float(configured.rate_to_cny)
        options.append({
            "country_code": country.code,
            "country_name": country.name_cn,
            "currency_code": country.currency_code,
            "currency_symbol": country.currency_symbol,
            "rate_to_cny": rate,
        })
    return options


def resolve_rate(db: Session, country_code: str | None) -> tuple[str | None, float | None]:
    """Return (currency_code, rate_to_cny) for a country; CN resolves to 1."""
    if not country_code:
        return None, None
    if country_code == CNY_COUNTRY_CODE:
        return CNY_CURRENCY_CODE, 1.0
    country = get_country(db, country_code)
    if country is None:
        return None, None
    rate = db.query(ExchangeRate).filter(ExchangeRate.country_code == country_code).first()
    if rate is None:
        return country.currency_code, None
    return rate.currency_code or country.currency_code, float(rate.rate_to_cny)


def amount_to_cny(amount: Any, rate: float | None) -> Optional[float]:
    if amount is None or rate is None:
        return None
    try:
        return round(float(amount) * float(rate), 2)
    except (TypeError, ValueError):
        return None


def row_currency_payload(db: Session, country_code: str | None, rate_map: dict[str, dict[str, Any]] | None = None) -> dict[str, Any]:
    """Return currency metadata for one row without issuing a query per row."""
    if rate_map is None:
        rate_map = build_rate_map(db)
    info = rate_map.get(country_code or "")
    return {
        "country_code": country_code,
        "currency_code": info["currency_code"] if info else None,
        "exchange_rate": info["rate_to_cny"] if info else None,
    }
