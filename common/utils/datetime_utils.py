from datetime import timezone as dt_timezone

from django.utils import timezone


# 将输入时间统一转换为带时区的 UTC 时间。
def normalize_datetime_to_utc(value):
    dt = value
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(dt_timezone.utc)
