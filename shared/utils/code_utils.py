def normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def strip_market_suffix(symbol: object) -> str:
    value = normalize_code(symbol)
    if "." not in value:
        return value
    return value.rsplit(".", 1)[0]


def resolve_short_code(short_code: object, symbol: object) -> str:
    return normalize_code(short_code) or strip_market_suffix(symbol)
