from decimal import Decimal

from shared.utils import normalize_code, to_decimal


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
