from __future__ import annotations

import csv
import logging
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone as dt_timezone
from pathlib import Path
from typing import Iterable
from zoneinfo import ZoneInfo

from django.conf import settings
from django.core.cache import cache

from accounts.services.quote_fetcher import (
    MARKET_CN,
    MARKET_CRYPTO,
    MARKET_FX,
    MARKET_HK,
    MARKET_US,
    should_fetch_market,
)

from .cache_keys import WATCHLIST_QUOTES_MARKET_KEY_PREFIX

logger = logging.getLogger(__name__)

MARKETS_WITH_CALENDAR = {MARKET_US, MARKET_CN, MARKET_HK}
DEFAULT_TICK_MINUTES = 5


@dataclass(frozen=True)
class CalendarDay:
    market: str
    trade_date: date
    timezone_name: str
    is_open: bool
    market_open_local: datetime | None
    market_close_local: datetime | None
    is_half_day: bool


@dataclass(frozen=True)
class GuardDecision:
    market: str
    should_pull: bool
    reason: str
    session: str = "none"


# 返回市场日历 CSV 所在目录。
def _calendar_dir() -> Path:
    raw = str(getattr(settings, "MARKET_CALENDAR_DIR", "") or "").strip()
    if raw:
        return Path(raw).resolve()
    return (Path(getattr(settings, "BASE_DIR", Path.cwd())) / "resource" / "data" / "market_calendars").resolve()


# 判断当前配置是否要求市场日历必须存在。
def _calendar_required() -> bool:
    return bool(getattr(settings, "MARKET_CALENDAR_REQUIRED", True))


# 判断缺失市场日历时是否允许回退到旧的时段判断逻辑。
def _fallback_on_missing_calendar() -> bool:
    return bool(getattr(settings, "MARKET_PULL_FALLBACK_ON_MISSING_CALENDAR", False))


# 读取任务调度周期分钟数配置。
def _task_tick_minutes() -> int:
    raw = getattr(settings, "MARKET_PULL_TASK_INTERVAL_MINUTES", DEFAULT_TICK_MINUTES)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = DEFAULT_TICK_MINUTES
    return max(1, min(value, 60))


# 读取外汇行情抓取周期分钟数配置。
def _fx_interval_minutes() -> int:
    raw = getattr(settings, "MARKET_FX_PULL_INTERVAL_MINUTES", 30)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 30
    return max(5, min(value, 240))


# 读取加密货币行情抓取周期分钟数配置。
def _crypto_interval_minutes() -> int:
    raw = getattr(settings, "MARKET_CRYPTO_PULL_INTERVAL_MINUTES", 10)
    try:
        value = int(raw)
    except (TypeError, ValueError):
        value = 10
    return max(1, min(value, 60))


# 统一市场代码格式为大写字符串。
def _normalize_market(market: object) -> str:
    return str(market or "").strip().upper()


# 将 ISO 时间字符串解析为带时区的时间对象。
def _to_aware_iso(value: str | None, tz_name: str) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=ZoneInfo(tz_name))
    return dt.astimezone(ZoneInfo(tz_name))


# 将常见布尔文本值解析为布尔类型。
def _parse_bool(value: object) -> bool:
    raw = str(value or "").strip().lower()
    return raw in {"1", "true", "yes", "y"}


# 从日历行数据中提取交易日期。
def _date_from_row(row: dict) -> date | None:
    raw = str(row.get("trade_date") or "").strip()
    if raw:
        try:
            return date.fromisoformat(raw)
        except ValueError:
            return None
    raw_open = str(row.get("market_open_local") or "").strip()
    if not raw_open:
        return None
    try:
        return datetime.fromisoformat(raw_open).date()
    except ValueError:
        return None


# 获取某个市场对应的日历文件列表。
def _calendar_files(market: str) -> list[Path]:
    base = _calendar_dir()
    if not base.exists():
        return []
    market_code = _normalize_market(market)
    direct = base / f"{market_code}.csv"
    files = []
    if direct.exists():
        files.append(direct)
    files.extend(sorted(base.glob(f"{market_code}_*.csv")))
    files.extend(sorted(base.glob(f"{market_code.lower()}_*.csv")))
    return files


# 生成日历文件签名，用于判断缓存是否失效。
def _files_signature(files: Iterable[Path]) -> tuple[tuple[str, int, int], ...]:
    signature = []
    for path in files:
        try:
            stat = path.stat()
        except OSError:
            continue
        signature.append((str(path), int(stat.st_mtime), int(stat.st_size)))
    return tuple(sorted(signature))


_CALENDAR_CACHE: dict[str, tuple[tuple[tuple[str, int, int], ...], dict[date, CalendarDay]]] = {}


# 读取并缓存某个市场的交易日历数据。
def _load_market_calendar(market: str) -> dict[date, CalendarDay]:
    market_code = _normalize_market(market)
    files = _calendar_files(market_code)
    signature = _files_signature(files)
    cached = _CALENDAR_CACHE.get(market_code)
    if cached and cached[0] == signature:
        return cached[1]

    table: dict[date, CalendarDay] = {}
    for path in files:
        try:
            with open(path, "r", encoding="utf-8-sig", newline="") as fp:
                reader = csv.DictReader(fp)
                for row in reader:
                    tz_name = str(row.get("timezone") or "").strip() or _default_timezone_name(market_code)
                    trade_date = _date_from_row(row)
                    if trade_date is None:
                        continue
                    table[trade_date] = CalendarDay(
                        market=market_code,
                        trade_date=trade_date,
                        timezone_name=tz_name,
                        is_open=_parse_bool(row.get("is_open")),
                        market_open_local=_to_aware_iso(row.get("market_open_local"), tz_name),
                        market_close_local=_to_aware_iso(row.get("market_close_local"), tz_name),
                        is_half_day=_parse_bool(row.get("is_half_day")),
                    )
        except Exception:
            logger.exception("calendar.guard.file_parse_error market=%s file=%s", market_code, path)

    _CALENDAR_CACHE[market_code] = (signature, table)
    return table


# 返回市场对应的默认时区名称。
def _default_timezone_name(market: str) -> str:
    if market == MARKET_US:
        return "America/New_York"
    if market == MARKET_HK:
        return "Asia/Hong_Kong"
    if market == MARKET_CN:
        return "Asia/Shanghai"
    return "UTC"


# 读取指定市场最近一次行情抓取时间。
def _last_market_pull_utc(market: str) -> datetime | None:
    key = f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}"
    payload = cache.get(key)
    if not isinstance(payload, dict):
        return None
    if "pulled_at" in payload:
        raw = payload.get("pulled_at")
    else:
        raw = payload.get("updated_at")
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=dt_timezone.utc)
    return dt.astimezone(dt_timezone.utc)


# 判断周期性抓取任务在当前时间点是否到期。
def _aligned_interval_due(*, now_local: datetime, last_pull_local: datetime | None, interval_minutes: int) -> bool:
    if interval_minutes <= 0:
        return False
    if (now_local.minute % interval_minutes) != 0:
        return False
    if last_pull_local is None:
        return True
    return (now_local - last_pull_local) >= timedelta(minutes=interval_minutes)


# 判断某个一次性触发时点是否已经到期。
def _one_shot_due(*, now_local: datetime, last_pull_local: datetime | None, target: time, tick_minutes: int) -> bool:
    start = now_local.replace(hour=target.hour, minute=target.minute, second=0, microsecond=0)
    end = start + timedelta(minutes=tick_minutes)
    if not (start <= now_local < end):
        return False
    if last_pull_local is None:
        return True
    return last_pull_local < start


# 依据市场日历和时段规则评估某个有交易日历市场是否应抓取行情。
def _evaluate_calendar_market(market: str, now_utc: datetime) -> GuardDecision:
    table = _load_market_calendar(market)
    if not table:
        if _calendar_required():
            if _fallback_on_missing_calendar():
                if should_fetch_market(market, now_utc):
                    return GuardDecision(market=market, should_pull=True, reason="fallback_without_calendar")
                return GuardDecision(market=market, should_pull=False, reason="fallback_outside_session")
            logger.error("calendar.guard.file_missing market=%s dir=%s", market, _calendar_dir())
            return GuardDecision(market=market, should_pull=False, reason="calendar_missing")
        if should_fetch_market(market, now_utc):
            return GuardDecision(market=market, should_pull=True, reason="calendar_optional_fallback")
        return GuardDecision(market=market, should_pull=False, reason="calendar_optional_fallback_skip")

    sample = next(iter(table.values()))
    tz = ZoneInfo(sample.timezone_name)
    now_local = now_utc.astimezone(tz)
    day = table.get(now_local.date())
    if day is None or not day.is_open:
        return GuardDecision(market=market, should_pull=False, reason="non_trading_day")

    last_pull_utc = _last_market_pull_utc(market)
    last_pull_local = last_pull_utc.astimezone(tz) if last_pull_utc else None
    tick_minutes = _task_tick_minutes()
    t = now_local.time()

    if market == MARKET_US:
        close_t = None
        if day.market_close_local:
            close_t = day.market_close_local.timetz().replace(tzinfo=None)
        if day.is_half_day and close_t and t >= close_t:
            return GuardDecision(market=market, should_pull=False, reason="after_half_day_close_guard")

        if time(4, 0) <= t < time(9, 30):
            due = _aligned_interval_due(now_local=now_local, last_pull_local=last_pull_local, interval_minutes=60)
            return GuardDecision(market=market, should_pull=due, reason="due" if due else "not_due", session="pre")
        if time(9, 30) <= t < time(16, 0):
            if close_t and t >= close_t:
                return GuardDecision(market=market, should_pull=False, reason="after_half_day_close", session="regular")
            due = _aligned_interval_due(now_local=now_local, last_pull_local=last_pull_local, interval_minutes=10)
            return GuardDecision(market=market, should_pull=due, reason="due" if due else "not_due", session="regular")
        if time(16, 0) <= t < time(20, 0):
            due = _aligned_interval_due(now_local=now_local, last_pull_local=last_pull_local, interval_minutes=60)
            return GuardDecision(market=market, should_pull=due, reason="due" if due else "not_due", session="post")
        return GuardDecision(market=market, should_pull=False, reason="outside_session")

    if market == MARKET_CN:
        if _one_shot_due(now_local=now_local, last_pull_local=last_pull_local, target=time(9, 25), tick_minutes=tick_minutes):
            return GuardDecision(market=market, should_pull=True, reason="due", session="pre")
        if (time(9, 30) <= t < time(11, 30)) or (time(13, 0) <= t < time(15, 0)):
            due = _aligned_interval_due(now_local=now_local, last_pull_local=last_pull_local, interval_minutes=10)
            return GuardDecision(market=market, should_pull=due, reason="due" if due else "not_due", session="regular")
        if _one_shot_due(now_local=now_local, last_pull_local=last_pull_local, target=time(15, 30), tick_minutes=tick_minutes):
            return GuardDecision(market=market, should_pull=True, reason="due", session="post")
        return GuardDecision(market=market, should_pull=False, reason="outside_session")

    if market == MARKET_HK:
        if _one_shot_due(now_local=now_local, last_pull_local=last_pull_local, target=time(9, 20), tick_minutes=tick_minutes):
            return GuardDecision(market=market, should_pull=True, reason="due", session="pre")
        if (time(9, 30) <= t < time(12, 0)) or (time(13, 0) <= t < time(16, 0)):
            due = _aligned_interval_due(now_local=now_local, last_pull_local=last_pull_local, interval_minutes=10)
            return GuardDecision(market=market, should_pull=due, reason="due" if due else "not_due", session="regular")
        if _one_shot_due(now_local=now_local, last_pull_local=last_pull_local, target=time(16, 10), tick_minutes=tick_minutes):
            return GuardDecision(market=market, should_pull=True, reason="due", session="post")
        return GuardDecision(market=market, should_pull=False, reason="outside_session")

    return GuardDecision(market=market, should_pull=False, reason="unsupported_market")


# 评估 24x7 或 24x5 市场在当前时间是否应抓取行情。
def _evaluate_always_open_market(market: str, now_utc: datetime) -> GuardDecision:
    if market == MARKET_CRYPTO:
        interval = _crypto_interval_minutes()
        last_pull = _last_market_pull_utc(market)
        due = _aligned_interval_due(
            now_local=now_utc.astimezone(dt_timezone.utc),
            last_pull_local=last_pull,
            interval_minutes=interval,
        )
        return GuardDecision(market=market, should_pull=due, reason="due" if due else "not_due", session="24x7")
    if market == MARKET_FX:
        if not should_fetch_market(market, now_utc):
            return GuardDecision(market=market, should_pull=False, reason="outside_session")
        interval = _fx_interval_minutes()
        last_pull = _last_market_pull_utc(market)
        due = _aligned_interval_due(
            now_local=now_utc.astimezone(dt_timezone.utc),
            last_pull_local=last_pull,
            interval_minutes=interval,
        )
        return GuardDecision(market=market, should_pull=due, reason="due" if due else "not_due", session="24x5")
    return GuardDecision(market=market, should_pull=False, reason="unsupported_market")


# 返回单个市场当前的行情抓取决策结果。
def market_guard_decision(market: str, now_utc: datetime | None = None) -> GuardDecision:
    now = now_utc or datetime.now(dt_timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=dt_timezone.utc)
    market_code = _normalize_market(market)

    if market_code in MARKETS_WITH_CALENDAR:
        return _evaluate_calendar_market(market_code, now)
    if market_code in {MARKET_CRYPTO, MARKET_FX}:
        return _evaluate_always_open_market(market_code, now)
    return GuardDecision(market=market_code, should_pull=False, reason="unsupported_market")


# 批量计算多个市场当前应抓取的市场集合及详细决策。
def resolve_due_markets(markets: Iterable[str], now_utc: datetime | None = None) -> tuple[set[str], dict[str, GuardDecision]]:
    due: set[str] = set()
    decisions: dict[str, GuardDecision] = {}
    for market in { _normalize_market(x) for x in markets if _normalize_market(x) }:
        decision = market_guard_decision(market, now_utc=now_utc)
        decisions[market] = decision
        if decision.should_pull:
            due.add(market)
    return due, decisions
