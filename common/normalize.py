from datetime import timezone as dt_timezone
from decimal import Decimal

from django.utils import timezone

US_EXCHANGE_SUFFIXES = frozenset({"US", "N", "A", "P", "Q", "O", "OQ", "OB", "PK", "TO"})


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


def normalize_decimal(value: Decimal) -> Decimal:
    return Decimal("0") if value.is_zero() else value


def normalize_usd_rates(raw_rates: object) -> dict[str, Decimal]:
    rates: dict[str, Decimal] = {"USD": Decimal("1")}
    if not isinstance(raw_rates, dict):
        return rates

    for code, raw_value in raw_rates.items():
        ccy = normalize_code(code)
        try:
            value = Decimal(str(raw_value))
        except Exception:
            continue
        if not ccy or value <= 0:
            continue
        rates[ccy] = value

    rates["USD"] = Decimal("1")
    return rates


def normalize_cn_code(raw_code: object) -> str:
    code = str(raw_code).strip()
    digits = "".join(ch for ch in code if ch.isdigit())
    if digits:
        return digits.zfill(6) if len(digits) <= 6 else digits
    return "".join(ch for ch in code.upper() if ch.isalnum())


def normalize_us_code(raw_code: object) -> str:
    code = normalize_code(raw_code)
    if not code:
        return ""

    parts = code.split(".")
    if len(parts) > 1 and parts[0].isdigit():
        code = ".".join(parts[1:])

    parts = code.split(".")
    if len(parts) > 1 and parts[-1] in US_EXCHANGE_SUFFIXES:
        code = ".".join(parts[:-1])

    code = code.replace(".", "-").replace("/", "-")
    return "".join(ch for ch in code if ch.isalnum() or ch == "-")
