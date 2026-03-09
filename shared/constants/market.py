from types import MappingProxyType


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
