from decimal import Decimal

from common.utils.code_utils import normalize_code
from common.utils.decimal_utils import to_decimal


# 将任意来源的美元汇率载荷标准化为 `币种 -> Decimal` 映射。
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

