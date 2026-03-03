def normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def strip_market_suffix(symbol: object) -> str:
    value = normalize_code(symbol)
    if "." not in value:
        return value
    return value.rsplit(".", 1)[0]
