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


# 根据市场代码返回默认计价币种，不存在时回退到默认值。
def market_currency(market: object, default: str = "") -> str:
    code = str(market or "").strip().upper()
    return MARKET_TO_CURRENCY.get(code, default)
