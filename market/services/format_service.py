from common.utils import resolve_short_code

from .quote_snapshot_service import safe_price_str


# 统一清洗行情行里的可空 logo 字段。
def format_quote_row(row: dict) -> dict:
    normalized_row = dict(row)
    normalized_row["logo_url"] = normalized_row.get("logo_url") or None
    normalized_row["logo_color"] = normalized_row.get("logo_color") or None
    return normalized_row


# 统一构造最新价接口的返回项。
def format_latest_quote_item(*, market: str, short_code: str, row: dict | None) -> dict:
    latest_price = safe_price_str(row.get("price")) if isinstance(row, dict) else None
    return {
        "market": market,
        "short_code": short_code,
        "latest_price": latest_price,
        "logo_url": (row.get("logo_url") or None) if isinstance(row, dict) else None,
        "logo_color": (row.get("logo_color") or None) if isinstance(row, dict) else None,
    }


# 统一构造自选添加接口里的标的信息返回结构。
def format_watchlist_instrument(instrument) -> dict:
    return {
        "symbol": instrument.symbol,
        "short_code": instrument.short_code,
        "name": instrument.name,
        "market": instrument.market,
        "logo_url": instrument.logo_url,
        "logo_color": instrument.logo_color,
    }


# 从原始快照列表中过滤当前用户允许看到的标的。
def filter_quotes(rows, allow_codes):
    if not isinstance(rows, list):
        return []

    filtered = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = resolve_short_code(row.get("short_code"), row.get("symbol"))
        if code in allow_codes:
            filtered.append(format_quote_row(row))
    return filtered

