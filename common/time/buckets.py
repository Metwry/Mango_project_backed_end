from datetime import datetime, timedelta, timezone as dt_timezone


# 将任意时间规范化为按分钟对齐的 UTC 时间。
def _as_utc_minute(dt: datetime) -> datetime:
    value = dt
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)


# 按快照粒度将时间向下对齐到对应时间桶起点。
def floor_bucket(dt: datetime, level: str) -> datetime:
    ts = _as_utc_minute(dt)
    if level == "M15":
        return ts.replace(minute=(ts.minute // 15) * 15)
    if level == "H4":
        return ts.replace(hour=(ts.hour // 4) * 4, minute=0)
    if level == "D1":
        return ts.replace(hour=0, minute=0)
    if level == "MON1":
        return ts.replace(day=1, hour=0, minute=0)
    return ts


# 返回当前时间桶的下一个时间桶起点。
def next_bucket(ts: datetime, level: str) -> datetime:
    if level == "M15":
        return ts + timedelta(minutes=15)
    if level == "H4":
        return ts + timedelta(hours=4)
    if level == "D1":
        return ts + timedelta(days=1)
    if level == "MON1":
        month = ts.month + 1
        year = ts.year
        if month == 13:
            month = 1
            year += 1
        return ts.replace(year=year, month=month, day=1)
    return ts


# 按快照粒度将时间向上对齐到最近的时间桶起点。
def ceil_bucket(dt: datetime, level: str) -> datetime:
    floored = floor_bucket(dt, level)
    raw = _as_utc_minute(dt)
    if floored < raw:
        return next_bucket(floored, level)
    return floored


# 构建起止时间之间的完整时间桶坐标轴。
def build_bucket_axis(start_time: datetime, end_time: datetime, level: str) -> tuple[list[datetime], datetime, datetime]:
    axis_start = ceil_bucket(start_time, level)
    axis_end = floor_bucket(end_time, level)
    if axis_start > axis_end:
        return [], axis_start, axis_end

    buckets: list[datetime] = []
    current = axis_start
    while current <= axis_end:
        buckets.append(current)
        current = next_bucket(current, level)
    return buckets, axis_start, axis_end
