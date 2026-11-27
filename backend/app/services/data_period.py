"""Business periods. Zero is the internal monthly sentinel, never a weekly input."""
from decimal import Decimal
from numbers import Real


def normalize_week(value, *, required=False) -> int:
    if value is None or isinstance(value, str) and not value.strip():
        if required:
            raise ValueError("周度数据缺少周次，请填写1～5的整数或对应数字字符串")
        return 0
    if isinstance(value, str):
        text = value.strip()
        if text in {"1", "2", "3", "4", "5"}:
            return int(text)
    elif not isinstance(value, bool) and isinstance(value, (Real, Decimal)):
        if value in (1, 2, 3, 4, 5):
            return int(value)
    raise ValueError(f"周次“{value}”格式不正确，请填写1～5的整数或对应数字字符串")


def period_key(month, week=0) -> str:
    return f"W:{month}:{int(week):02d}" if week else f"M:{month}"


def job_week(job) -> int:
    return int(getattr(job, "week_of_month", None) or 0)


def apply_record_period(record, *, period_type=None, default_week=None, row_number=None):
    """Validate before deduplication, including records which would be skipped."""
    try:
        if period_type not in (None, "month", "week"):
            raise ValueError("数据粒度只能为month（月度）或week（周度）")
        week = normalize_week(record.get("week"))
        fallback = normalize_week(default_week)
        if week and fallback and week != fallback:
            raise ValueError("文件周次与指定周次不一致，请修正后重试")
        week = week or fallback
        if period_type == "month" and week:
            raise ValueError("月度数据不能填写周次，请切换为周度或修正周字段映射")
        if period_type == "week" and not week:
            normalize_week(None, required=True)
        if week:
            month = record.get("month")
            if isinstance(month, bool) or month is None or int(month) != month or not (100001 <= int(month) <= 999912 and 1 <= int(month) % 100 <= 12):
                raise ValueError("周度数据月份无效，请填写YYYYMM格式的业务月份")
        record["week_of_month"] = week
        record["week"] = str(week) if week else None
        return record
    except (ValueError, TypeError, OverflowError) as exc:
        prefix = f"第{row_number}行：" if row_number is not None else ""
        raise ValueError(f"{prefix}{exc}") from exc


def filter_period(query, model, period_type=None, week=None):
    if period_type == "month":
        query = query.filter(model.week_of_month == 0)
    elif period_type == "week":
        query = query.filter(model.week_of_month > 0)
    if week is not None:
        query = query.filter(model.week_of_month == normalize_week(week, required=True))
    return query


def inspect_upload_periods(path, mapping, ignored, *, period_type=None, default_week=None, filename_month=None):
    from app.services.excel_parser import iter_source_chunks, _clean

    fields = {target: col for col, target in mapping.items() if col not in set(ignored)}
    mode = period_type or ("week" if "week" in fields or default_week is not None else "month")
    # Validate even an empty file or a manual value unused because every row has a week.
    normalize_week(default_week)
    if mode not in ("month", "week"):
        raise ValueError("数据粒度只能为month（月度）或week（周度）")
    if mode == "month" and "week" not in fields and default_week is None:
        return {"period_type": "month", "weeks": []}
    weeks = set()
    for frame in iter_source_chunks(path, preserve_values=True, typed_columns={fields.get("week")}):
        for number, row in frame.iterrows():
            month = filename_month if filename_month is not None else _clean(row.get(fields.get("month")))
            try:
                numeric = Decimal(str(month))
                month = int(numeric) if numeric.is_finite() and numeric == int(numeric) else None
            except Exception:
                month = None
            record = {"month": month, "week": _clean(row.get(fields.get("week")))}
            apply_record_period(record, period_type=mode, default_week=default_week, row_number=int(number))
            if record["week_of_month"]:
                weeks.add(record["week_of_month"])
    return {"period_type": mode, "weeks": sorted(weeks)}
