from __future__ import annotations

import json
import logging
import re
import urllib.parse
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
import pandas as pd

try:
    import yfinance as yf
except Exception:
    yf = None

logger = logging.getLogger(__name__)

MARKET_CRYPTO = "CRYPTO"
MARKET_CN = "CN"
MARKET_HK = "HK"
MARKET_US = "US"
MARKET_FX = "FX"

# --- 代理配置 ---
PROXY_PORT = 7897
PROXIES = {
    "http": f"http://127.0.0.1:{PROXY_PORT}",
    "https": f"http://127.0.0.1:{PROXY_PORT}",
}


@dataclass
class QuoteOut:
    short_code: str
    name: str
    prev_close: Optional[float]
    day_high: Optional[float]
    day_low: Optional[float]
    price: Optional[float]
    pct: Optional[float]
    volume: Optional[float]


def _strip_symbol_suffix(symbol: str) -> str:
    s = symbol.strip().upper()
    if "." not in s: return s
    code, suffix = s.rsplit(".", 1)
    return code if suffix.isalpha() else s


def _safe_float(x: Any) -> Optional[float]:
    try:
        return None if x is None or str(x).strip() in ("", "nan", "NaN") else float(x)
    except Exception:
        return None


def _to_billion_amount(amount: Optional[float]) -> Optional[float]:
    if amount is None or amount <= 0:
        return None
    return round(amount / 100000000.0, 2)


def _is_weekday(dt_local: datetime) -> bool:
    return dt_local.weekday() < 5


def should_fetch_market(market: str, now_utc: Optional[datetime] = None) -> bool:
    now_utc = now_utc or datetime.now(timezone.utc)
    if market == MARKET_CRYPTO: return True
    if market == MARKET_US:
        dt = now_utc.astimezone(ZoneInfo("America/New_York"))
        if not _is_weekday(dt): return False
        return time(9, 30) <= dt.time() <= time(16, 0)
    if market == MARKET_CN:
        dt = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
        if not _is_weekday(dt): return False
        t = dt.time()
        return (time(9, 30) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 0))
    if market == MARKET_HK:
        dt = now_utc.astimezone(ZoneInfo("Asia/Hong_Kong"))
        if not _is_weekday(dt): return False
        t = dt.time()
        return (time(9, 30) <= t <= time(12, 0)) or (time(13, 0) <= t <= time(16, 0))
    if market == MARKET_FX:
        dt = now_utc.astimezone(ZoneInfo("UTC"))
        return _is_weekday(dt)
    return False


# ==================== 股票市场 (新浪直连) ====================

def _to_sina_symbol(market: str, symbol: str) -> str:
    s = symbol.strip().upper()
    if market == MARKET_CN:
        m = re.fullmatch(r"(?P<code>\d{6})(?:\.(?P<suffix>[A-Z]+))?", s)
        if not m: return ""
        code = m.group("code")
        suffix = (m.group("suffix") or "").upper()
        if suffix in {"SH", "SS", "6"}: return f"sh{code}"
        if suffix == "SZ" or code.startswith(("0", "3")): return f"sz{code}"
        if suffix == "BJ" or code.startswith(("4", "8", "9")): return f"bj{code}"
    elif market == MARKET_HK:
        core = s[:-3] if s.endswith(".HK") else s
        digits = re.sub(r"\D", "", core)
        return f"rt_hk{digits.zfill(5)}"
    elif market == MARKET_US:
        core = s[:-3] if s.endswith(".US") else s
        core = core.replace(".", "$").lower()
        return f"gb_{core}"
    return ""


def fetch_stocks_sina(market: str, items: List[Tuple[str, str, str]]) -> List[QuoteOut]:
    results = []
    if not items: return results

    sina_symbols = []
    symbol_map = {}
    for original_symbol, short_code, name in items:
        s_code = _to_sina_symbol(market, original_symbol)
        if s_code:
            sina_symbols.append(s_code)
            symbol_map[s_code] = (short_code or _strip_symbol_suffix(original_symbol), name)

    if not sina_symbols: return results

    url = f"http://hq.sinajs.cn/list={','.join(sina_symbols)}"
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}

    try:
        with requests.Session() as session:
            session.trust_env = False
            resp = session.get(url, headers=headers, timeout=5)
            resp.raise_for_status()
            resp.encoding = "gbk"
            text = resp.text
    except Exception as exc:
        logger.error(f"新浪接口请求失败 market={market} err={exc}")
        return results

    for line in text.splitlines():
        if not line.startswith("var hq_str_"): continue
        parts = line.split("=", 1)
        if len(parts) != 2: continue

        s_code = parts[0].replace("var hq_str_", "").strip()
        fields = parts[1].strip('";').split(",")
        if len(fields) < 5: continue

        short_code, name = symbol_map.get(s_code, (s_code.replace("rt_hk", "").replace("gb_", ""), ""))
        prev_close = day_high = day_low = price = volume_shares = turnover_amount = None

        if market == MARKET_CN:
            name = fields[0] if not name else name
            prev_close, price = _safe_float(fields[2]), _safe_float(fields[3])
            day_high, day_low = _safe_float(fields[4]), _safe_float(fields[5])
            volume_shares = _safe_float(fields[8])
            turnover_amount = _safe_float(fields[9]) if len(fields) > 9 else None
        elif market == MARKET_HK:
            name = fields[1] if not name else name
            prev_close, price = _safe_float(fields[3]), _safe_float(fields[6])
            day_high, day_low = _safe_float(fields[4]), _safe_float(fields[5])
            volume_shares = _safe_float(fields[12])
            turnover_amount = _safe_float(fields[11]) if len(fields) > 11 else None
        elif market == MARKET_US:
            name = fields[0] if not name else name
            price = _safe_float(fields[1])
            day_high, day_low = _safe_float(fields[6]), _safe_float(fields[7])
            volume_shares = _safe_float(fields[10])
            prev_close = _safe_float(fields[26])

        if price == 0 and prev_close is not None:
            price = day_high = day_low = prev_close

        if (turnover_amount is None or turnover_amount <= 0) and price is not None and volume_shares is not None:
            turnover_amount = price * volume_shares

        pct = None
        if price is not None and prev_close and prev_close != 0:
            pct = (price - prev_close) / prev_close * 100.0

        volume_out = _to_billion_amount(turnover_amount)

        results.append(QuoteOut(
            short_code=short_code, name=name, prev_close=prev_close,
            day_high=day_high, day_low=day_low, price=price, pct=pct, volume=volume_out
        ))
    return results


# ==================== 加密货币 (币安) ====================

def fetch_crypto_quotes_binance(items: List[Tuple[str, str, str]]) -> List[QuoteOut]:
    results = []
    if not items: return results

    binance_symbols = []
    symbol_map = {}
    usdt_rows: List[Tuple[str, str]] = []
    for original_symbol, short_code, name in items:
        base_coin = short_code or _strip_symbol_suffix(original_symbol)
        if base_coin.upper() == "USDT":
            usdt_rows.append((short_code or "USDT", name or "Tether"))
            continue
        b_symbol = f"{base_coin.upper()}USDT"
        binance_symbols.append(b_symbol)
        symbol_map[b_symbol] = (short_code, name)

    if binance_symbols:
        encoded_symbols = urllib.parse.quote(json.dumps(binance_symbols).replace(" ", ""))
        url = f"https://api4.binance.com/api/v3/ticker/24hr?symbols={encoded_symbols}"

        try:
            resp = requests.get(url, timeout=10, proxies=PROXIES)
            resp.raise_for_status()
            payload = resp.json()
            data = payload if isinstance(payload, list) else [payload]
        except Exception as exc:
            logger.error(f"币安 API 请求失败 err={exc}")
            data = []

        for item in data:
            b_symbol = item.get("symbol")
            if b_symbol not in symbol_map: continue
            short_code, name = symbol_map[b_symbol]

            prev_close = _safe_float(item.get("prevClosePrice"))
            price = _safe_float(item.get("lastPrice"))
            day_high = _safe_float(item.get("highPrice"))
            day_low = _safe_float(item.get("lowPrice"))
            pct = _safe_float(item.get("priceChangePercent"))
            quote_volume = _safe_float(item.get("quoteVolume"))

            results.append(QuoteOut(
                short_code=short_code, name=name, prev_close=prev_close,
                day_high=day_high, day_low=day_low, price=price, pct=pct,
                volume=quote_volume / 1e8 if quote_volume else None
            ))

    if usdt_rows:
        usdt_price = usdt_prev_close = usdt_day_high = usdt_day_low = usdt_pct = None
        try:
            usdt_url = "https://api4.binance.com/api/v3/ticker/24hr?symbol=USDCUSDT"
            usdt_resp = requests.get(usdt_url, timeout=10, proxies=PROXIES)
            usdt_resp.raise_for_status()
            usdt_data = usdt_resp.json()
            usdt_price = _safe_float(usdt_data.get("lastPrice"))
            usdt_prev_close = _safe_float(usdt_data.get("prevClosePrice"))
            usdt_day_high = _safe_float(usdt_data.get("highPrice"))
            usdt_day_low = _safe_float(usdt_data.get("lowPrice"))
            usdt_pct = _safe_float(usdt_data.get("priceChangePercent"))
        except Exception as exc:
            logger.warning(f"USDT 专用行情获取失败，回退固定值 err={exc}")

        if usdt_price is None:
            usdt_price = 1.0
        if usdt_prev_close is None:
            usdt_prev_close = 1.0
        if usdt_day_high is None:
            usdt_day_high = usdt_price
        if usdt_day_low is None:
            usdt_day_low = usdt_price

        for short_code, name in usdt_rows:
            results.append(QuoteOut(
                short_code=short_code,
                name=name,
                prev_close=usdt_prev_close,
                day_high=usdt_day_high,
                day_low=usdt_day_low,
                price=usdt_price,
                pct=usdt_pct,
                volume=None,
            ))
    return results


# ==================== 外汇主从容灾架构 (新浪 + yfinance) ====================

def _to_sina_fx_symbol(symbol: str) -> str:
    s = symbol.strip().upper()
    if s.endswith(".FX"):
        s = s[:-3]
    m = re.fullmatch(r"([A-Z]{3})[/_-]?([A-Z]{3})", s)
    if not m:
        return ""
    return f"fx_s{m.group(1).lower()}{m.group(2).lower()}"


def fetch_fx_quotes_sina(items: List[Tuple[str, str, str]]) -> List[QuoteOut]:
    """主接口：新浪外汇"""
    results = []
    if not items:
        return results

    sina_symbols = []
    symbol_map = {}
    for symbol, short_code, name in items:
        sina_symbol = _to_sina_fx_symbol(symbol)
        if not sina_symbol:
            continue
        sina_symbols.append(sina_symbol)
        symbol_map[sina_symbol] = (short_code or _strip_symbol_suffix(symbol), name)

    if not sina_symbols:
        return results

    url = f"https://hq.sinajs.cn/list={','.join(sina_symbols)}"
    headers = {"Referer": "https://finance.sina.com.cn", "User-Agent": "Mozilla/5.0"}

    try:
        with requests.Session() as session:
            session.trust_env = False
            resp = session.get(url, headers=headers, timeout=8)
            resp.raise_for_status()
            resp.encoding = "gbk"
            text = resp.text
    except Exception as exc:
        logger.error(f"新浪外汇接口请求失败 err={exc}")
        return results

    for line in text.splitlines():
        if not line.startswith("var hq_str_"):
            continue
        parts = line.split("=", 1)
        if len(parts) != 2:
            continue

        sina_symbol = parts[0].replace("var hq_str_", "").strip()
        short_code, name = symbol_map.get(sina_symbol, (sina_symbol.replace("fx_s", "").upper(), ""))

        fields = parts[1].strip('";').split(",")
        if len(fields) < 10:
            continue

        # 新浪外汇字段：8最新价, 5昨收, 6最高, 7最低, 9名称
        price = _safe_float(fields[8]) or _safe_float(fields[1])
        prev_close = _safe_float(fields[5])
        day_high = _safe_float(fields[6])
        day_low = _safe_float(fields[7])
        if not name:
            name = fields[9]

        pct = None
        if price is not None and prev_close and prev_close != 0:
            pct = (price - prev_close) / prev_close * 100.0

        results.append(QuoteOut(
            short_code=short_code, name=name or short_code, prev_close=prev_close,
            day_high=day_high, day_low=day_low, price=price, pct=pct, volume=None
        ))
    return results


def fetch_fx_quotes_yfinance(items: List[Tuple[str, str, str]]) -> List[QuoteOut]:
    """备用接口：yfinance"""
    results = []
    if not items or yf is None: return results

    yf_tickers_map = {}
    for symbol, short_code, name in items:
        core = symbol[:-3] if symbol.endswith(".FX") else symbol
        yf_ticker = f"{core.replace('/', '')}=X"
        yf_tickers_map[yf_ticker] = (short_code or _strip_symbol_suffix(symbol), name)

    try:
        session = requests.Session()
        session.headers.update({"User-Agent": "Mozilla/5.0"})
        if PROXIES: session.proxies.update(PROXIES)
        adapter = HTTPAdapter(max_retries=Retry(total=3, backoff_factor=0.5))
        session.mount("http://", adapter)
        session.mount("https://", adapter)

        df = yf.download(
            list(yf_tickers_map.keys()), period="5d", progress=False,
            session=session, ignore_tz=True
        )
    except Exception as exc:
        logger.warning(f"外汇 yfinance 备用接口彻底失败: {exc}")
        return results

    if df.empty: return results
    is_multi = isinstance(df.columns, pd.MultiIndex)

    for yf_code, (short_code, name) in yf_tickers_map.items():
        try:
            if is_multi:
                if yf_code not in df['Close'].columns: continue
                s_close = df['Close'][yf_code].dropna()
                s_high = df['High'][yf_code].dropna()
                s_low = df['Low'][yf_code].dropna()
            else:
                s_close = df['Close'].dropna()
                s_high = df['High'].dropna()
                s_low = df['Low'].dropna()

            if len(s_close) < 1: continue

            price = _safe_float(s_close.iloc[-1])
            day_high = _safe_float(s_high.iloc[-1])
            day_low = _safe_float(s_low.iloc[-1])
            prev_close = _safe_float(s_close.iloc[-2]) if len(s_close) >= 2 else price

            pct = None
            if price is not None and prev_close and prev_close != 0:
                pct = (price - prev_close) / prev_close * 100.0

            results.append(QuoteOut(
                short_code=short_code, name=name, prev_close=prev_close,
                day_high=day_high, day_low=day_low, price=price, pct=pct, volume=None
            ))
        except Exception:
            continue
    return results


def fetch_fx_quotes_with_fallback(items: List[Tuple[str, str, str]]) -> List[QuoteOut]:
    """主从切换调度器"""
    quotes = fetch_fx_quotes_sina(items)

    if quotes:
        return quotes

    logger.warning("新浪外汇未返回数据或发生错误，无缝降级至 yfinance 兜底...")
    return fetch_fx_quotes_yfinance(items)


# ==================== 统一入口 ====================

USD_MAINSTREAM_CURRENCIES = (
    "CNY",
    "EUR",
    "JPY",
    "GBP",
    "HKD",
)


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


def get_unique_instruments_from_watchlist() -> List[Tuple[str, str, str, str, Optional[str], Optional[str]]]:
    # Backward-compatible alias: quote pulling now uses unified subscription set.
    return get_unique_instruments_from_subscriptions()


def pull_usd_exchange_rates(seed_rows: Optional[List[dict]] = None) -> Dict[str, float]:
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

def pull_single_instrument_quote(symbol: str, short_code: str, name: str, market: str) -> Optional[dict]:
    """处理用户手动添加新代码时的突发查询"""
    item = [(symbol, short_code, name)]
    if market in (MARKET_CN, MARKET_HK, MARKET_US):
        quotes = fetch_stocks_sina(market, item)
    elif market == MARKET_CRYPTO:
        quotes = fetch_crypto_quotes_binance(item)
    elif market == MARKET_FX:
        quotes = fetch_fx_quotes_with_fallback(item)  # 使用容灾包装函数
    else:
        return None

    return asdict(quotes[0]) if quotes else None


# 配合你现有的数据库，保留批量入口
def pull_watchlist_quotes(now_utc: Optional[datetime] = None, force_fetch_all_markets: bool = False) -> Dict[
    str, List[dict]]:
    """定时任务批量拉取入口"""
    now_utc = now_utc or datetime.now(timezone.utc)
    rows = get_unique_instruments_from_subscriptions()

    if not rows: return {}

    by_market: Dict[str, List[Tuple[str, str, str]]] = {}
    for symbol, short_code, name, market, _, _ in rows:
        by_market.setdefault(market, []).append((symbol, short_code, name))

    out: Dict[str, List[dict]] = {}

    for market, items in by_market.items():
        if not force_fetch_all_markets and not should_fetch_market(market, now_utc):
            logger.warning("休市跳过行情拉取 market=%s 当前UTC时间=%s", market, now_utc.isoformat())
            continue

        if market in (MARKET_CN, MARKET_HK, MARKET_US):
            quotes = fetch_stocks_sina(market, items)
        elif market == MARKET_CRYPTO:
            quotes = fetch_crypto_quotes_binance(items)
        elif market == MARKET_FX:
            quotes = fetch_fx_quotes_with_fallback(items)  # 使用容灾包装函数

        out[market] = [asdict(q) for q in quotes]

    return out
