from decimal import Decimal, ROUND_HALF_UP


def to_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


def trim_decimal(value: Decimal) -> Decimal:
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in {"", "-0"}:
        s = "0"
    return Decimal(s)


def trim_decimal_str(value: Decimal) -> str:
    return str(trim_decimal(value))


def quantize_decimal(value: Decimal, precision: Decimal) -> Decimal:
    return value.quantize(precision, rounding=ROUND_HALF_UP)
