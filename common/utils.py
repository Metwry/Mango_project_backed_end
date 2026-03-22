from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType
from typing import Any

from django import VERSION as DJANGO_VERSION
from django.db import models
from django.db.models import Q

from .normalize import normalize_decimal


def safe_payload_data(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}

def to_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def format_decimal_str(value: Decimal) -> str:
    text = format(normalize_decimal(value), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def quantize_decimal(value: Decimal, precision: Decimal) -> Decimal:
    return value.quantize(precision, rounding=ROUND_HALF_UP)


MARKET_TO_CURRENCY = MappingProxyType(
    {
        "US": "USD",
        "CN": "CNY",
        "HK": "HKD",
        "CRYPTO": "USD",
        "FX": "USD",
    }
)


def market_currency(market: object, default: str = "") -> str:
    code = str(market or "").strip().upper()
    return MARKET_TO_CURRENCY.get(code, default)


def check_constraint(*, expr: Q, name: str) -> models.CheckConstraint:
    if DJANGO_VERSION >= (5, 1):
        return models.CheckConstraint(condition=expr, name=name)
    return models.CheckConstraint(check=expr, name=name)

def _as_utc_minute(dt: datetime) -> datetime:
    value = dt
    if value.tzinfo is None:
        value = value.replace(tzinfo=dt_timezone.utc)
    return value.astimezone(dt_timezone.utc).replace(second=0, microsecond=0)


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


def ceil_bucket(dt: datetime, level: str) -> datetime:
    floored = floor_bucket(dt, level)
    raw = _as_utc_minute(dt)
    if floored < raw:
        return next_bucket(floored, level)
    return floored


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


def _format_log_value(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def _format_log_fields(**fields: Any) -> str:
    items = []
    for key in sorted(fields.keys()):
        items.append(f"{key}={_format_log_value(fields[key])}")
    return " ".join(items)


def log_info(logger, event: str, **fields: Any) -> None:
    payload = _format_log_fields(**fields)
    if payload:
        logger.info("%s %s", event, payload)
        return
    logger.info("%s", event)
