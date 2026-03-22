from datetime import datetime, timedelta, timezone as dt_timezone
from decimal import Decimal, ROUND_HALF_UP
from types import MappingProxyType

from django import VERSION as DJANGO_VERSION
from django.db import models
from django.db.models import Q
from django.utils import timezone


def safe_payload_data(payload: object) -> dict:
    if not isinstance(payload, dict):
        return {}
    data = payload.get("data")
    return data if isinstance(data, dict) else {}


def normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def strip_market_suffix(symbol: object) -> str:
    value = normalize_code(symbol)
    if "." not in value:
        return value
    return value.rsplit(".", 1)[0]


def resolve_short_code(short_code: object, symbol: object) -> str:
    return normalize_code(short_code) or strip_market_suffix(symbol)


def normalize_datetime_to_utc(value):
    dt = value
    if timezone.is_naive(dt):
        dt = timezone.make_aware(dt, timezone.get_current_timezone())
    return dt.astimezone(dt_timezone.utc)


def to_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def normalize_decimal(value: Decimal) -> Decimal:
    return Decimal("0") if value.is_zero() else value


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


def normalize_usd_rates(raw_rates: object) -> dict[str, Decimal]:
    rates: dict[str, Decimal] = {"USD": Decimal("1")}
    if not isinstance(raw_rates, dict):
        return rates

    for code, raw_value in raw_rates.items():
        ccy = normalize_code(code)
        value = to_decimal(raw_value)
        if not ccy or value is None or value <= 0:
            continue
        rates[ccy] = value

    rates["USD"] = Decimal("1")
    return rates


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
