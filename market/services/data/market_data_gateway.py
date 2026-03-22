from __future__ import annotations
import pandas as pd
import yfinance as yf
from dataclasses import asdict
from decimal import Decimal

from common.utils import format_decimal_str, to_decimal
from market.services.market_utils import (
    MARKET_CN,
    MARKET_CRYPTO,
    MARKET_FX,
    MARKET_HK,
    MARKET_US,
)

from .quote_providers import fetch_crypto_quotes_binance, fetch_fx_quotes_with_fallback, fetch_stocks_sina


MarketQuoteItem = tuple[str, str, str]
IndexQuoteItem = tuple[str, str, int, str]


# 按市场类型分发到对应的行情 provider 批量拉取行情。
def fetch_market_quotes(market: str, items: list[MarketQuoteItem]):
    market_code = str(market or "").strip().upper()
    if market_code in (MARKET_CN, MARKET_HK, MARKET_US):
        return fetch_stocks_sina(market_code, items)
    if market_code == MARKET_CRYPTO:
        return fetch_crypto_quotes_binance(items)
    if market_code == MARKET_FX:
        return fetch_fx_quotes_with_fallback(items)
    return []


# 拉取单个标的行情并转换成字典结果。
def pull_single_market_quote(symbol: str, short_code: str, name: str, market: str) -> dict | None:
    quotes = fetch_market_quotes(market, [(symbol, short_code, name)])
    if not quotes:
        return None
    return asdict(quotes[0])


# 将原始数值安全地格式化为字符串形式的小数。
def _safe_str_decimal(value: object) -> str | None:
    parsed = to_decimal(value)
    return format_decimal_str(parsed) if parsed is not None else None


# 构造指数行情拉取失败时的空白占位行。
def _build_null_index_row(symbol: str, instrument_id: int, name: str) -> dict:
    return {
        "symbol": symbol,
        "instrument_id": instrument_id,
        "name": name,
        "prev_close": None,
        "day_high": None,
        "day_low": None,
        "pct": None,
    }


# 从 yfinance 返回的 DataFrame 中提取指定字段序列。
def _extract_series_value(frame, field: str, provider_symbol: str):
    columns = getattr(frame, "columns", None)
    if columns is None:
        return None
    is_multi = pd is not None and isinstance(columns, pd.MultiIndex)
    try:
        if is_multi:
            series = frame[field][provider_symbol].dropna()
        else:
            series = frame[field].dropna()
    except Exception:
        return None
    if len(series) == 0:
        return None
    return series


# 批量拉取核心指数日线快照并整理为统一行结构。
def fetch_index_snapshot_rows(items: list[IndexQuoteItem]) -> list[dict]:
    if not items:
        return []
    if yf is None:
        raise RuntimeError("yfinance is unavailable")

    provider_symbols: list[str] = []
    item_by_provider: dict[str, IndexQuoteItem] = {}
    for symbol, provider_symbol, instrument_id, name in items:
        if not provider_symbol:
            continue
        provider_symbols.append(provider_symbol)
        item_by_provider[provider_symbol] = (symbol, provider_symbol, instrument_id, name)

    if not provider_symbols:
        return []

    frame = yf.download(
        provider_symbols,
        period="5d",
        interval="1d",
        progress=False,
        auto_adjust=False,
        group_by="column",
        threads=False,
    )
    if frame is None or getattr(frame, "empty", True):
        raise RuntimeError("index quote source returned empty data")

    rows: list[dict] = []
    for provider_symbol, (symbol, _, instrument_id, name) in item_by_provider.items():
        close_series = _extract_series_value(frame, "Close", provider_symbol)
        high_series = _extract_series_value(frame, "High", provider_symbol)
        low_series = _extract_series_value(frame, "Low", provider_symbol)
        if close_series is None or high_series is None or low_series is None:
            rows.append(_build_null_index_row(symbol, instrument_id, name))
            continue

        last_close = close_series.iloc[-1]
        prev_close = close_series.iloc[-2] if len(close_series) >= 2 else last_close
        prev_decimal = to_decimal(prev_close)
        last_decimal = to_decimal(last_close)
        pct = None
        if prev_decimal not in (None, Decimal("0")) and last_decimal is not None:
            pct = format_decimal_str(((last_decimal - prev_decimal) / prev_decimal) * Decimal("100"))

        rows.append(
            {
                "symbol": symbol,
                "instrument_id": instrument_id,
                "name": name,
                "prev_close": _safe_str_decimal(prev_close),
                "day_high": _safe_str_decimal(high_series.iloc[-1]),
                "day_low": _safe_str_decimal(low_series.iloc[-1]),
                "pct": pct,
            }
        )

    return rows
