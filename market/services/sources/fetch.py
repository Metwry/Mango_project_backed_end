from __future__ import annotations

import logging
import re
from dataclasses import asdict
from typing import Dict, List, Optional, Tuple

from .gateway import fetch_market_quotes, pull_single_market_quote
from .providers import (
    MARKET_FX,
    _safe_float,
)

logger = logging.getLogger(__name__)

USD_MAINSTREAM_CURRENCIES = (
    "CNY",
    "EUR",
    "JPY",
    "GBP",
    "HKD",
)


# 将外汇代码解析为基础币和计价币。
def _parse_fx_pair(raw: object) -> Optional[Tuple[str, str]]:
    if raw is None:
        return None

    code = str(raw).strip().upper()
    if not code:
        return None

    if "." in code:
        left, suffix = code.rsplit(".", 1)
        if suffix.isalpha():
            code = left

    match = re.fullmatch(r"([A-Z]{3})[/_-]?([A-Z]{3})", code)
    if not match:
        return None
    return match.group(1), match.group(2)


# 从行情行中提取相对美元的汇率映射。
def _collect_usd_rates_from_rows(rows: List[dict]) -> Dict[str, float]:
    rates: Dict[str, float] = {}
    for row in rows:
        if not isinstance(row, dict):
            continue

        pair = _parse_fx_pair(row.get("short_code")) or _parse_fx_pair(row.get("symbol"))
        if not pair:
            continue

        base, quote = pair
        price = _safe_float(row.get("price"))
        if price is None or price <= 0:
            continue

        if base == "USD":
            rates[quote] = price
        elif quote == "USD":
            rates[base] = 1.0 / price
    return rates


# 读取全局订阅中去重后的标的信息。
def get_unique_instruments_from_subscriptions() -> List[Tuple[str, str, str, str]]:
    from market.models import UserInstrumentSubscription

    return list(
        UserInstrumentSubscription.objects
        .filter(instrument__is_active=True)
        .values_list(
            "instrument__symbol",
            "instrument__short_code",
            "instrument__name",
            "instrument__market",
        )
        .distinct()
    )


# 拉取并补齐美元对主流货币的汇率数据。
def pull_usd_exchange_rates(seed_rows: Optional[List[dict]] = None) -> Dict[str, float]:
    rates: Dict[str, float] = {"USD": 1.0}

    if isinstance(seed_rows, list):
        rates.update(_collect_usd_rates_from_rows(seed_rows))

    targets = [ccy for ccy in USD_MAINSTREAM_CURRENCIES if ccy not in rates]
    if targets:
        forward_items = [(f"USD/{ccy}.FX", f"USD/{ccy}", f"USD/{ccy}") for ccy in targets]
        forward_quotes = fetch_market_quotes(MARKET_FX, forward_items)
        rates.update(_collect_usd_rates_from_rows([asdict(q) for q in forward_quotes]))

    remaining = [ccy for ccy in USD_MAINSTREAM_CURRENCIES if ccy not in rates]
    if remaining:
        inverse_items = [(f"{ccy}/USD.FX", f"{ccy}/USD", f"{ccy}/USD") for ccy in remaining]
        inverse_quotes = fetch_market_quotes(MARKET_FX, inverse_items)
        rates.update(_collect_usd_rates_from_rows([asdict(q) for q in inverse_quotes]))

    rates = {code: value for code, value in rates.items() if value > 0}
    rates["USD"] = 1.0
    return rates


# 通过统一行情入口批量拉取指定市场行情。
def _fetch_market_quotes(market: str, items: List[Tuple[str, str, str]]):
    return fetch_market_quotes(market, items)


# 拉取单个标的的最新行情。
def pull_single_instrument_quote(symbol: str, short_code: str, name: str, market: str) -> Optional[dict]:
    return pull_single_market_quote(symbol, short_code, name, market)


# 按市场批量拉取全局自选订阅行情。
def pull_watchlist_quotes(
    allowed_markets: Optional[set[str] | list[str] | tuple[str, ...]] = None,
) -> Dict[str, List[dict]]:
    rows = get_unique_instruments_from_subscriptions()
    if not rows:
        return {}

    by_market: Dict[str, List[Tuple[str, str, str]]] = {}
    for symbol, short_code, name, market in rows:
        by_market.setdefault(market, []).append((symbol, short_code, name))

    allowed = None
    if allowed_markets is not None:
        allowed = set(allowed_markets)

    out: Dict[str, List[dict]] = {}
    for market, items in by_market.items():
        if allowed is not None and market not in allowed:
            logger.info("calendar guard skip market=%s reason=not_in_due_markets", market)
            continue
        quotes = _fetch_market_quotes(market, items)
        out[market] = [asdict(q) for q in quotes]

    return out
