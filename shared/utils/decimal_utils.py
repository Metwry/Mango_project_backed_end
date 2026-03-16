from decimal import Decimal, ROUND_HALF_UP


# 将任意输入安全转换为 Decimal，无法转换时返回空值。
def to_decimal(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None


# 去掉 Decimal 尾部无意义的 0，并统一消除 `-0` 情况。
def trim_decimal(value: Decimal) -> Decimal:
    s = format(value, "f")
    if "." in s:
        s = s.rstrip("0").rstrip(".")
    if s in {"", "-0"}:
        s = "0"
    return Decimal(s)


# 返回去除多余尾零后的 Decimal 字符串表示。
def trim_decimal_str(value: Decimal) -> str:
    return str(trim_decimal(value))


# 按指定精度对 Decimal 执行四舍五入量化。
def quantize_decimal(value: Decimal, precision: Decimal) -> Decimal:
    return value.quantize(precision, rounding=ROUND_HALF_UP)
