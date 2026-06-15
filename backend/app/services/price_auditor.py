from decimal import Decimal
from typing import Any

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models.analytics_db import AnalyticsSession, PublishedItem
from app.models.schemas import MatchResult, ModelRecord, RawDataRecord


AUDIT_STATUSES = ("url_matched", "matched", "confirmed")


def _previous_months(month: int, count: int = 6) -> list[int]:
    year = month // 100
    month_num = month % 100
    months = []

    for _ in range(count):
        month_num -= 1
        if month_num == 0:
            year -= 1
            month_num = 12
        months.append(year * 100 + month_num)

    return months


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    return Decimal(str(value))


def _flag_for_price(current_price, avg_price) -> str:
    current = _to_decimal(current_price)
    average = _to_decimal(avg_price)

    if current is None or average is None or average <= 0:
        return "no_history"
    if current > average * Decimal("1.2"):
        return "high"
    if current < average * Decimal("0.8"):
        return "low"
    return "ok"


def _round_price_ref(avg_price) -> Decimal:
    average = _to_decimal(avg_price)
    if average is None:
        return Decimal("0.00")
    return average.quantize(Decimal("0.01"))


def audit_price(db: Session, match_result_ids: list[int], commit: bool = True) -> dict:
    if not match_result_ids:
        return {"audited": 0}

    rows = (
        db.query(MatchResult, RawDataRecord, ModelRecord)
        .join(RawDataRecord, MatchResult.raw_data_id == RawDataRecord.id)
        .join(ModelRecord, MatchResult.model_id == ModelRecord.id)
        .filter(MatchResult.id.in_(match_result_ids))
        .filter(MatchResult.match_status.in_(AUDIT_STATUSES))
        .all()
    )

    analytics_db = AnalyticsSession()
    try:
        for match_result, raw_data, model in rows:
            if raw_data.price is None or raw_data.month is None or not model.model_code:
                match_result.price_flag = "no_history"
                match_result.price_ref = None
                continue

            avg_price = (
                analytics_db.query(func.avg(PublishedItem.price))
                .filter(PublishedItem.model_code == model.model_code)
                .filter(PublishedItem.month.in_(_previous_months(raw_data.month)))
                .filter(PublishedItem.price.isnot(None))
                .scalar()
            )

            flag = _flag_for_price(raw_data.price, avg_price)
            match_result.price_flag = flag
            match_result.price_ref = None if flag == "no_history" else _round_price_ref(avg_price)

        if commit:
            db.commit()
    finally:
        analytics_db.close()

    return {"audited": len(rows)}
