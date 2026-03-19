# 将代码类输入统一清洗为去空格的大写字符串。
def normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


# 去掉统一代码中的市场后缀，得到短代码。
def strip_market_suffix(symbol: object) -> str:
    value = normalize_code(symbol)
    if "." not in value:
        return value
    return value.rsplit(".", 1)[0]


# 优先返回显式短代码，否则从统一代码中推导短代码。
def resolve_short_code(short_code: object, symbol: object) -> str:
    return normalize_code(short_code) or strip_market_suffix(symbol)
