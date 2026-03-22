from __future__ import annotations

from common.utils import normalize_code, resolve_short_code


def quote_code(row: dict) -> str:
    return resolve_short_code(row.get("short_code"), row.get("symbol"))


def market_rows(data: dict, market: str) -> list[dict]:
    rows = data.get(market, [])
    return rows if isinstance(rows, list) else []


def snapshot_code_set(rows: list[dict]) -> set[str]:
    return {code for row in rows if (code := quote_code(row))}


def index_rows_by_code(rows: list[dict]) -> dict[str, dict]:
    return {code: row for row in rows if (code := quote_code(row))}


def find_quote_by_code(rows: object, short_code: str) -> dict | None:
    if not isinstance(rows, list):
        return None
    code = normalize_code(short_code)
    for row in rows:
        if normalize_code(row.get("short_code")) == code:
            return row
    return None


def upsert_market_quote(data: dict, market: str, quote_row: dict) -> None:
    market_quotes = data.setdefault(market, [])
    code = normalize_code(quote_row.get("short_code"))
    for idx, row in enumerate(market_quotes):
        if normalize_code(row.get("short_code")) == code:
            market_quotes[idx] = quote_row
            return

    market_quotes.append(quote_row)


def pop_quote_by_code(data: dict, market: str, short_code: str) -> dict | None:
    rows = market_rows(data, market)
    code = normalize_code(short_code)
    kept = []
    removed_row = None
    for row in rows:
        row_code = quote_code(row)
        if row_code == code:
            if removed_row is None:
                removed_row = row
            continue
        kept.append(row)

    if removed_row is None:
        return None

    if kept:
        data[market] = kept
    else:
        data.pop(market, None)
    return removed_row
