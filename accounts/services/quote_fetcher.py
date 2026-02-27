from __future__ import annotations

import logging
import re
from dataclasses import asdict, dataclass
from datetime import datetime, time, timezone
from typing import Any, Dict, List, Optional, Tuple
from zoneinfo import ZoneInfo

import requests

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

USD_RATE_TARGET_CURRENCIES = ("USD", "CNY", "EUR", "JPY", "GBP", "HKD")
USD_RATE_PREFETCH_ITEMS: Dict[str, Tuple[str, str, str]] = {
    "CNY": ("USD/CNH.FX", "USD/CNH", "US Dollar / Chinese Yuan Offshore"),
    "EUR": ("EUR/USD.FX", "EUR/USD", "Euro / US Dollar"),
    "JPY": ("USD/JPY.FX", "USD/JPY", "US Dollar / Japanese Yen"),
    "GBP": ("GBP/USD.FX", "GBP/USD", "British Pound / US Dollar"),
    "HKD": ("USD/HKD.FX", "USD/HKD", "US Dollar / Hong Kong Dollar"),
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
    volume: Optional[float]  # 股票: 万股, 加密货币: 亿USD, 外汇: None


def _strip_symbol_suffix(symbol: str) -> str:
    """将标准代码后缀剥离成短代码，例如 AAPL.US -> AAPL。"""
    s = symbol.strip().upper()
    if "." not in s:
        return s
    code, suffix = s.rsplit(".", 1)
    return code if suffix.isalpha() else s


def _get_text_without_env_proxy(
    url: str,
    headers: Dict[str, str],
    timeout: int,
    encoding: str = "gbk",
) -> Optional[str]:
    """
    使用独立 Session 禁用系统代理，避免修改 requests 全局行为。
    """
    try:
        with requests.Session() as session:
            session.trust_env = False
            resp = session.get(url, headers=headers, timeout=timeout)
            resp.raise_for_status()
            resp.encoding = encoding
            return resp.text
    except Exception as exc:
        logger.error("请求接口失败 url=%s err=%s", url, exc)
        return None


def _is_weekday(dt_local: datetime) -> bool:
    return dt_local.weekday() < 5


def should_fetch_market(market: str, now_utc: Optional[datetime] = None) -> bool:
    """判断当前时间是否是该市场的交易时间"""
    now_utc = now_utc or datetime.now(timezone.utc)

    if market == MARKET_CRYPTO:
        return True  # 7x24小时

    if market == MARKET_US:
        dt = now_utc.astimezone(ZoneInfo("America/New_York"))
        if not _is_weekday(dt): return False
        return time(9, 30) <= dt.time() <= time(16, 0)

    if market == MARKET_CN:
        dt = now_utc.astimezone(ZoneInfo("Asia/Shanghai"))
        if not _is_weekday(dt): return False
        t = dt.time()
        # 涵盖早盘和午盘
        return (time(9, 30) <= t <= time(11, 30)) or (time(13, 0) <= t <= time(15, 0))

    if market == MARKET_HK:
        dt = now_utc.astimezone(ZoneInfo("Asia/Hong_Kong"))
        if not _is_weekday(dt): return False
        t = dt.time()
        return (time(9, 30) <= t <= time(12, 0)) or (time(13, 0) <= t <= time(16, 0))

    if market == MARKET_FX:
        dt = now_utc.astimezone(ZoneInfo("UTC"))
        return _is_weekday(dt)  # 外汇 5x24 小时

    return False


def normalize_yfinance_ticker(market: str, symbol: str) -> str:
    """专门为 yfinance 格式化 ticker"""
    s = symbol.strip().upper()
    if market == MARKET_HK:
        m = re.match(r"^(\d+)\.HK$", s)
        if m:
            digits = m.group(1).lstrip("0") or "0"
            return f"{digits.zfill(4)}.HK"  # e.g., 00001.HK -> 0001.HK
        return s
    if market == MARKET_US:
        return s[:-3] if s.endswith(".US") else s
    if market == MARKET_FX:
        core = s[:-3] if s.endswith(".FX") else s
        return f"{core.replace('/', '')}=X"  # e.g., GBP/USD.FX -> GBPUSD=X
    if market == MARKET_CRYPTO:
        core = s[:-7] if s.endswith(".CRYPTO") else s
        return f"{core}-USD"  # e.g., BTC.CRYPTO -> BTC-USD
    return s


def _safe_float(x: Any) -> Optional[float]:
    try:
        return None if x is None or str(x).strip() in ("", "nan", "NaN") else float(x)
    except Exception:
        return None


def _extract_fx_pair(row: dict) -> Optional[Tuple[str, str]]:
    for key in ("short_code", "symbol"):
        raw = str(row.get(key) or "").strip().upper()
        if not raw:
            continue

        if raw.endswith(".FX"):
            raw = raw[:-3]
        if raw.endswith("=X"):
            raw = raw[:-2]

        if "/" in raw:
            left, right = raw.split("/", 1)
            if len(left) == 3 and len(right) == 3 and left.isalpha() and right.isalpha():
                return left, right
            continue

        if len(raw) == 6 and raw.isalpha():
            return raw[:3], raw[3:]

    return None


def build_usd_exchange_rates_from_rows(rows: List[dict]) -> Dict[str, float]:
    rates: Dict[str, float] = {"USD": 1.0}

    for row in rows:
        if not isinstance(row, dict):
            continue

        pair = _extract_fx_pair(row)
        if not pair:
            continue

        left, right = pair
        price = _safe_float(row.get("price"))
        if price is None or price <= 0:
            continue

        # left/right = pair in form LEFT/RIGHT, and price means RIGHT per LEFT.
        if right == "USD" and left != "USD":
            rates[left] = price
        elif left == "USD" and right != "USD":
            rates[right] = 1.0 / price

    # Some providers expose CNH rather than CNY; align for account currency conversion.
    if "CNY" not in rates and "CNH" in rates:
        rates["CNY"] = rates["CNH"]

    rates["USD"] = 1.0
    return rates


def pull_usd_exchange_rates(seed_rows: Optional[List[dict]] = None) -> Dict[str, float]:
    rates = build_usd_exchange_rates_from_rows(seed_rows or [])
    missing = {code for code in USD_RATE_TARGET_CURRENCIES if code not in rates}

    if missing:
        items = [USD_RATE_PREFETCH_ITEMS[code] for code in missing if code in USD_RATE_PREFETCH_ITEMS]
        fetched = fetch_global_quotes_yfinance(MARKET_FX, items) if items else []
        if fetched:
            fetched_rows = [asdict(x) for x in fetched]
            rates.update(build_usd_exchange_rates_from_rows(fetched_rows))

    rates.setdefault("USD", 1.0)
    if "CNY" not in rates and "CNH" in rates:
        rates["CNY"] = rates["CNH"]

    cleaned: Dict[str, float] = {}
    for code, raw in rates.items():
        value = _safe_float(raw)
        if value is None or value <= 0:
            continue
        cleaned[str(code).strip().upper()] = value

    cleaned["USD"] = 1.0
    return cleaned


def get_unique_instruments_from_watchlist() -> List[Tuple[str, str, str, str]]:
    """从数据库中提取去重后的关注标的 (symbol, short_code, name, market)。"""

    # 延迟导入，防止单独运行测试脚本时报 ModuleNotFoundError
    from accounts.models import WatchlistItem

    qs = (
        WatchlistItem.objects
        .values_list(
            "instrument__symbol",
            "instrument__short_code",
            "instrument__name",
            "instrument__market",
        )
        .distinct()
    )
    return list(qs)


def _to_sina_symbol(symbol: str) -> str:
    """将标准代码转换为新浪接口需要的格式 (如 000001.SZ -> sz000001)"""
    s = symbol.strip().upper()
    m = re.fullmatch(r"(?P<code>\d{6})(?:\.(?P<suffix>[A-Z]+))?", s)
    if not m:
        return ""

    code = m.group("code")
    suffix = (m.group("suffix") or "").upper()

    if suffix in {"SH", "SS"}: return f"sh{code}"
    if suffix == "SZ": return f"sz{code}"
    if suffix == "BJ": return f"bj{code}"

    if code.startswith("6"): return f"sh{code}"
    if code.startswith(("0", "3")): return f"sz{code}"
    if code.startswith(("4", "8", "9")): return f"bj{code}"
    return ""


def fetch_cn_quotes_sina(items: List[Tuple[str, str, str]]) -> List[QuoteOut]:
    """
    [极致优化] 使用新浪财经 API 批量拉取 A 股，无缝穿透代理且速度极快。
    """
    results = []
    if not items:
        return results

    sina_symbols = []
    symbol_map = {}

    for original_symbol, short_code, name in items:
        s_code = _to_sina_symbol(original_symbol)
        if s_code:
            sina_symbols.append(s_code)
            symbol_map[s_code] = (short_code or _strip_symbol_suffix(original_symbol), name)

    if not sina_symbols:
        return results

    # 批量拼接请求，如 list=sh600000,sz000001
    url = f"http://hq.sinajs.cn/list={','.join(sina_symbols)}"
    headers = {
        "Referer": "https://finance.sina.com.cn",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"
    }

    text = _get_text_without_env_proxy(url=url, headers=headers, timeout=5, encoding="gbk")
    if not text:
        return results

    for line in text.splitlines():
        if not line.startswith("var hq_str_"):
            continue

        parts = line.split("=", 1)
        if len(parts) != 2:
            continue

        s_code = parts[0].replace("var hq_str_", "").strip()
        data_str = parts[1].strip('";')
        fields = data_str.split(",")
        if len(fields) < 10:
            continue
        short_code, name = symbol_map.get(s_code, (s_code[2:] if len(s_code) > 2 else s_code, ""))

        # 1:今开, 2:昨收, 3:最新价, 4:最高, 5:最低, 8:成交量(股)
        prev_close = _safe_float(fields[2])
        price = _safe_float(fields[3])
        day_high = _safe_float(fields[4])
        day_low = _safe_float(fields[5])
        volume_shares = _safe_float(fields[8])

        # 停牌兼容
        if price == 0 and prev_close is not None:
            price = prev_close
            day_high = prev_close
            day_low = prev_close

        pct = None
        if price is not None and prev_close and prev_close != 0:
            pct = (price - prev_close) / prev_close * 100.0

        # 新浪返回单位是股，换算为万股
        volume_out = volume_shares / 10000.0 if volume_shares else None

        results.append(QuoteOut(
            short_code=short_code,
            name=name,
            prev_close=prev_close,
            day_high=day_high,
            day_low=day_low,
            price=price,
            pct=pct,
            volume=volume_out
        ))

    return results


def fetch_global_quotes_yfinance(market: str, items: List[Tuple[str, str, str]]) -> List[QuoteOut]:
    """
    处理美股、港股、加密货币和外汇 (基于 yfinance)
    """
    results = []
    if not items or yf is None:
        return results

    # 构建 YF 专属 Tickers
    yf_tickers_map = {}
    for symbol, short_code, name in items:
        yf_ticker = normalize_yfinance_ticker(market, symbol)
        # 保留首个映射，避免同一 yfinance ticker 被重复覆盖
        yf_tickers_map.setdefault(
            yf_ticker,
            (short_code or _strip_symbol_suffix(symbol), name),
        )
    yf_symbols = list(yf_tickers_map.keys())

    try:
        tk = yf.Tickers(" ".join(yf_symbols))
    except Exception as exc:
        logger.warning(f"yfinance 初始化失败 market={market}: {exc}")
        return results

    for yf_code, (short_code, name) in yf_tickers_map.items():
        t = tk.tickers.get(yf_code)
        if not t:
            continue

        prev_close = day_high = day_low = price = volume_raw = None

        try:
            # fast_info 获取实时数据最快
            fi = getattr(t, "fast_info", None)
            if fi:
                prev_close = _safe_float(fi.get("previous_close"))
                day_high = _safe_float(fi.get("day_high"))
                day_low = _safe_float(fi.get("day_low"))
                price = _safe_float(fi.get("last_price"))
                volume_raw = _safe_float(fi.get("volume"))

            # 兜底：如果 fast_info 失败或为空，尝试使用 info
            if price is None:
                info = t.info or {}
                prev_close = _safe_float(info.get("previousClose"))
                day_high = _safe_float(info.get("dayHigh"))
                day_low = _safe_float(info.get("dayLow"))
                price = _safe_float(info.get("currentPrice") or info.get("regularMarketPrice"))
                volume_raw = _safe_float(info.get("volume") or info.get("regularMarketVolume"))

        except Exception as e:
            logger.warning(f"获取 {yf_code} 详情失败: {e}")
            continue

        # 计算涨跌幅
        pct = None
        if price is not None and prev_close and prev_close != 0:
            pct = (price - prev_close) / prev_close * 100.0

        # 处理成交量换算规则
        volume_out = None
        if market in (MARKET_US, MARKET_HK):
            # 美股/港股原始 volume 单位为股，转换为万股
            volume_out = volume_raw / 10000.0 if volume_raw else None
        elif market == MARKET_CRYPTO:
            # 加密货币 volume 为 24h 法币计价总额(USD)，转换为 亿 USD
            volume_out = volume_raw / 1e8 if volume_raw else None
        elif market == MARKET_FX:
            # 外汇放空
            volume_out = None

        results.append(QuoteOut(
            short_code=short_code,
            name=name,
            prev_close=prev_close,
            day_high=day_high,
            day_low=day_low,
            price=price,
            pct=pct,
            volume=volume_out
        ))

    return results


def pull_watchlist_quotes(
    now_utc: Optional[datetime] = None,
    force_fetch_all_markets: bool = False,
) -> Dict[str, List[dict]]:
    """
    主入口：拉取所有关注列表的行情，每 10 分钟调度一次
    """
    now_utc = now_utc or datetime.now(timezone.utc)

    rows = get_unique_instruments_from_watchlist()
    if not rows:
        return {}

    # 按市场分组
    by_market: Dict[str, List[Tuple[str, str, str]]] = {}
    for symbol, short_code, name, market in rows:
        by_market.setdefault(market, []).append((symbol, short_code, name))

    out: Dict[str, List[dict]] = {}

    for market, items in by_market.items():
        # 休市检查 (如果测试时想强制拉取，可以注释掉下面两行)
        if not force_fetch_all_markets and not should_fetch_market(market, now_utc):
            logger.info(f"{market} 市场处于休市状态，跳过拉取。")
            continue

        # 智能路由：A股走新浪直连，其他走雅虎
        if market == MARKET_CN:
            quotes = fetch_cn_quotes_sina(items)
        else:
            quotes = fetch_global_quotes_yfinance(market, items)

        out[market] = [asdict(q) for q in quotes]

    return out


def pull_single_instrument_quote(
    symbol: str,
    short_code: str,
    name: str,
    market: str,
) -> Optional[dict]:
    """
    单独拉取一个标的行情（不做交易时段检查），用于用户新增自选时快速回填。
    """
    item = [(symbol, short_code, name)]
    if market == MARKET_CN:
        quotes = fetch_cn_quotes_sina(item)
    else:
        quotes = fetch_global_quotes_yfinance(market, item)

    if not quotes:
        return None
    return asdict(quotes[0])
