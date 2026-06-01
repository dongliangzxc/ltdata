from datetime import datetime, timedelta


BEIJING_OFFSET = timedelta(hours=8)


def format_beijing_datetime(value: datetime | None) -> str | None:
    if value is None:
        return None
    return (value + BEIJING_OFFSET).strftime("%Y-%m-%d %H:%M:%S")
