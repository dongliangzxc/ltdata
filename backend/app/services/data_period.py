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


def normalize_week_selection(values) -> list[int]:
    if values is None:
        return []
    if not isinstance(values, list):
        raise ValueError("筛选周次必须是1～5组成的数组，例如[1, 3]")
    return sorted({normalize_week(value, required=True) for value in values})


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


def inspect_upload_periods(path, mapping, ignored, *, period_type=None, default_week=None, filename_month=None, selected_weeks=None):
    from app.services.excel_parser import iter_source_chunks, _clean

    fields = {target: col for col, target in mapping.items() if col not in set(ignored)}
    selected = normalize_week_selection(selected_weeks)
    mode = period_type or ("week" if "week" in fields or default_week is not None or selected else "month")
    # Validate even an empty file or a manual value unused because every row has a week.
    normalize_week(default_week)
    if mode not in ("month", "week"):
        raise ValueError("数据粒度只能为month（月度）或week（周度）")
    if selected and (mode != "week" or "week" not in fields):
        raise ValueError("筛选周次需要选择周度并映射文件中的周次列；无周次列时只能统一指定一个周次")
    if selected and default_week is not None:
        raise ValueError("不能同时筛选文件周次和统一指定周次")
    if mode == "month" and "week" not in fields and default_week is None:
        return {"period_type": "month", "weeks": []}
    weeks = set()
    source_rows = selected_rows = 0
    for frame in iter_source_chunks(path, preserve_values=True, typed_columns={fields.get("week")}):
        for number, row in frame.iterrows():
            source_rows += 1
            source_week = _clean(row.get(fields.get("week")))
            if selected:
                try:
                    included = normalize_week(source_week, required=True) in selected
                except ValueError as exc:
                    raise ValueError(f"第{int(number)}行：{exc}") from exc
                if not included:
                    continue
            month = filename_month if filename_month is not None else _clean(row.get(fields.get("month")))
            try:
                numeric = Decimal(str(month))
                month = int(numeric) if numeric.is_finite() and numeric == int(numeric) else None
            except Exception:
                month = None
            record = {"month": month, "week": source_week}
            apply_record_period(record, period_type=mode, default_week=default_week, row_number=int(number))
            if record["week_of_month"]:
                weeks.add(record["week_of_month"])
            selected_rows += 1
    summary = {"period_type": mode, "weeks": sorted(weeks)}
    if selected:
        if not selected_rows:
            raise ValueError("文件中没有所选周次的数据，请调整选择或检查周次列")
        summary.update(selected_rows=selected_rows, excluded_rows=source_rows - selected_rows, selected_weeks=selected)
    return summary
