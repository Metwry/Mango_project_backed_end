from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from django.conf import settings

from .quote_providers import (
    MARKET_CN,
    MARKET_CRYPTO,
    MARKET_FX,
    MARKET_HK,
    MARKET_US,
    _safe_float,
    _strip_symbol_suffix,
    fetch_crypto_quotes_binance,
    fetch_fx_quotes_with_fallback,
    fetch_stocks_sina,
    should_fetch_market,
)

logger = logging.getLogger(__name__)

# ==================== 统一入口 ====================

USD_MAINSTREAM_CURRENCIES = (
    "CNY",
    "EUR",
    "JPY",
    "GBP",
    "HKD",
)
FAKE_USD_RATES = {
    "USD": 1.0,
    "CNY": 7.12,
    "EUR": 0.92,
    "JPY": 150.0,
    "GBP": 0.79,
    "HKD": 7.82,
}


# 返回当前配置的行情提供方模式。
def _quote_provider_mode() -> str:
    return str(getattr(settings, "MARKET_QUOTE_PROVIDER", "real") or "real").strip().lower()


# 判断当前是否启用假行情提供方。
def _use_fake_provider() -> bool:
    return _quote_provider_mode() == "fake"


# 为给定文本生成稳定哈希，用于构造可重复的假行情波动。
def _stable_hash(text: str) -> int:
    digest = hashlib.sha256(text.encode("utf-8")).hexdigest()
    return int(digest[:12], 16)


# 将当前时间归并到按分钟切分的假行情时间桶。
def _fake_bucket(now_utc: datetime) -> int:
    return int(now_utc.timestamp() // 60)


# 从外汇代码中解析基础币种和计价币种。
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

    m = re.fullmatch(r"([A-Z]{3})[/_-]?([A-Z]{3})", code)
    if not m:
        return None
    return m.group(1), m.group(2)


# 为外汇短代码生成假行情价格。
def _fake_fx_price(short_code: str) -> float:
    pair = _parse_fx_pair(short_code)
    if not pair:
        return 1.0
    base, quote = pair
    if base == quote:
        return 1.0
    base_rate = FAKE_USD_RATES.get(base)
    quote_rate = FAKE_USD_RATES.get(quote)
    if base_rate is None or quote_rate is None or base_rate <= 0 or quote_rate <= 0:
        return 1.0
    if base == "USD":
        return float(quote_rate)
    if quote == "USD":
        return float(1.0 / base_rate)
    # cross via USD
    return float(quote_rate / base_rate)


# 按市场与代码生成稳定波动的假行情价格。
def _fake_market_price(market: str, short_code: str, bucket: int) -> float:
    market_code = str(market or "").upper()
    code = str(short_code or "").upper()
    if market_code == MARKET_FX:
        base = _fake_fx_price(code)
    elif market_code == MARKET_CRYPTO:
        baseline = 500 + (_stable_hash(code) % 50000)
        base = float(baseline)
    else:
        baseline = 20 + (_stable_hash(code) % 400)
        base = float(baseline)

    oscillation = ((bucket + (_stable_hash(code + market_code) % 37)) % 21 - 10) / 1000.0
    price = base * (1.0 + oscillation)
    return round(max(price, 0.0001), 6)


# 组装单条假行情结果。
def _build_fake_quote_row(*, market: str, symbol: str, short_code: str, name: str, now_utc: datetime) -> dict:
    code = short_code or _strip_symbol_suffix(symbol)
    bucket = _fake_bucket(now_utc)
    price = _fake_market_price(market, code, bucket)
    prev_close = round(price * 0.9975, 6)
    day_high = round(max(price, prev_close) * 1.003, 6)
    day_low = round(min(price, prev_close) * 0.997, 6)
    pct = round(((price - prev_close) / prev_close) * 100.0, 4) if prev_close else None
    vol_seed = (_stable_hash(f"{market}:{code}:{bucket}") % 5000) + 100
    volume = round(vol_seed / 100.0, 2)
    return {
        "short_code": code,
        "name": name or code,
        "prev_close": prev_close,
        "day_high": day_high,
        "day_low": day_low,
        "price": price,
        "pct": pct,
        "volume": volume,
    }


# 按市场批量生成订阅标的的假行情快照。
def _pull_watchlist_quotes_fake(
    *,
    now_utc: datetime,
    rows: List[Tuple[str, str, str, str, Optional[str], Optional[str]]],
    force_fetch_all_markets: bool,
    allowed_markets: Optional[set[str] | list[str] | tuple[str, ...]],
) -> Dict[str, List[dict]]:
    by_market: Dict[str, List[Tuple[str, str, str]]] = {}
    for symbol, short_code, name, market, _, _ in rows:
        by_market.setdefault(market, []).append((symbol, short_code, name))

    allowed = None
    if allowed_markets is not None:
        allowed = {str(m).strip().upper() for m in allowed_markets if str(m).strip()}

    out: Dict[str, List[dict]] = {}
    for market, items in by_market.items():
        if allowed is not None and market not in allowed:
            continue
        if allowed is None and not force_fetch_all_markets and not should_fetch_market(market, now_utc):
            continue
        out[market] = [
            _build_fake_quote_row(
                market=market,
                symbol=symbol,
                short_code=short_code,
                name=name,
                now_utc=now_utc,
            )
            for symbol, short_code, name in items
        ]
    return out


# 从外汇行情行中提取美元基准汇率。
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


# 读取所有订阅标的并去重后返回基础元数据。
def get_unique_instruments_from_subscriptions() -> List[Tuple[str, str, str, str, Optional[str], Optional[str]]]:
    from market.models import UserInstrumentSubscription

    rows = (
        UserInstrumentSubscription.objects
        .select_related("instrument")
        .filter(instrument__is_active=True)
        .values_list(
            "instrument__symbol",
            "instrument__short_code",
            "instrument__name",
            "instrument__market",
            "instrument__logo_url",
            "instrument__logo_color",
        )
        .distinct()
    )

    out: List[Tuple[str, str, str, str, Optional[str], Optional[str]]] = []
    for symbol, short_code, name, market, logo_url, logo_color in rows:
        symbol_val = str(symbol or "").strip().upper()
        short_code_val = str(short_code or "").strip().upper()
        market_val = str(market or "").strip().upper()
        logo_url_val = str(logo_url or "").strip() or None
        logo_color_val = str(logo_color or "").strip() or None
        if not symbol_val or not market_val:
            continue
        out.append((symbol_val, short_code_val, str(name or ""), market_val, logo_url_val, logo_color_val))
    return out


# 拉取或推导美元对主流币种的汇率表。
def pull_usd_exchange_rates(seed_rows: Optional[List[dict]] = None) -> Dict[str, float]:
    if _use_fake_provider():
        return dict(FAKE_USD_RATES)

    rates: Dict[str, float] = {"USD": 1.0}

    if isinstance(seed_rows, list):
        rates.update(_collect_usd_rates_from_rows(seed_rows))

    targets = [ccy for ccy in USD_MAINSTREAM_CURRENCIES if ccy not in rates]
    if targets:
        forward_items = [(f"USD/{ccy}.FX", f"USD/{ccy}", f"USD/{ccy}") for ccy in targets]
        forward_quotes = fetch_fx_quotes_with_fallback(forward_items)
        rates.update(_collect_usd_rates_from_rows([asdict(q) for q in forward_quotes]))

    remaining = [ccy for ccy in USD_MAINSTREAM_CURRENCIES if ccy not in rates]
    if remaining:
        inverse_items = [(f"{ccy}/USD.FX", f"{ccy}/USD", f"{ccy}/USD") for ccy in remaining]
        inverse_quotes = fetch_fx_quotes_with_fallback(inverse_items)
        rates.update(_collect_usd_rates_from_rows([asdict(q) for q in inverse_quotes]))

    rates = {code: value for code, value in rates.items() if value > 0}
    rates["USD"] = 1.0
    return rates


def _fetch_market_quotes(market: str, items: List[Tuple[str, str, str]]):
    if market in (MARKET_CN, MARKET_HK, MARKET_US):
        return fetch_stocks_sina(market, items)
    if market == MARKET_CRYPTO:
        return fetch_crypto_quotes_binance(items)
    if market == MARKET_FX:
        return fetch_fx_quotes_with_fallback(items)
    return []

# 拉取单个标的的最新行情，用于手动添加后的即时补齐。
def pull_single_instrument_quote(symbol: str, short_code: str, name: str, market: str) -> Optional[dict]:
    """处理用户手动添加新代码时的突发查询"""
    if _use_fake_provider():
        now_utc = datetime.now(timezone.utc)
        return _build_fake_quote_row(
            market=market,
            symbol=symbol,
            short_code=short_code,
            name=name,
            now_utc=now_utc,
        )

    item = [(symbol, short_code, name)]
    quotes = _fetch_market_quotes(market, item)
    if not quotes:
        return None

    return asdict(quotes[0]) if quotes else None


# 配合你现有的数据库，保留批量入口
# 按市场批量拉取当前订阅标的的行情快照。
def pull_watchlist_quotes(
    now_utc: Optional[datetime] = None,
    force_fetch_all_markets: bool = False,
    allowed_markets: Optional[set[str] | list[str] | tuple[str, ...]] = None,
) -> Dict[str, List[dict]]:
    """定时任务批量拉取入口"""
    now_utc = now_utc or datetime.now(timezone.utc)
    rows = get_unique_instruments_from_subscriptions()

    if not rows:
        return {}

    if _use_fake_provider():
        return _pull_watchlist_quotes_fake(
            now_utc=now_utc,
            rows=rows,
            force_fetch_all_markets=force_fetch_all_markets,
            allowed_markets=allowed_markets,
        )

    by_market: Dict[str, List[Tuple[str, str, str]]] = {}
    for symbol, short_code, name, market, _, _ in rows:
        by_market.setdefault(market, []).append((symbol, short_code, name))

    out: Dict[str, List[dict]] = {}

    allowed = None
    if allowed_markets is not None:
        allowed = {str(m).strip().upper() for m in allowed_markets if str(m).strip()}

    for market, items in by_market.items():
        if allowed is not None and market not in allowed:
            logger.info("calendar guard skip market=%s reason=not_in_due_markets", market)
            continue

        if allowed is None and not force_fetch_all_markets and not should_fetch_market(market, now_utc):
            logger.warning("休市跳过行情拉取 market=%s 当前UTC时间=%s", market, now_utc.isoformat())
            continue

        quotes = _fetch_market_quotes(market, items)
        out[market] = [asdict(q) for q in quotes]

    return out
