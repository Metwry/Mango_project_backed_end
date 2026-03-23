from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone

from django.core.cache import cache
from django.utils import timezone

from common.normalize import normalize_code, resolve_short_code
from common.utils import log_info, safe_payload_data

from ..pricing.cache import (
    UTC8,
    WATCHLIST_QUOTES_KEY,
    get_market_data_payload,
    index_rows_by_code,
    instrument_market_cache_key,
    market_rows,
    quote_code,
    snapshot_code_set,
)
from ..instruments.subscriptions import global_subscription_meta_by_market
from ..pricing.schedule import GuardDecision, resolve_due_markets
from ..sources.fetch import pull_single_instrument_quote, pull_watchlist_quotes

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _PullContext:
    now_local: datetime
    previous_data: dict[str, list[dict]]
    subscription_meta: dict[str, dict[str, dict]]
    subscription_codes: dict[str, set[str]]


@dataclass(frozen=True)
class _PullPlan:
    due_markets: set[str]
    guard_decisions: dict[str, GuardDecision]


# 构造无订阅场景下的空市场快照。
def _empty_market_payload(now_local: datetime) -> dict:
    return {
        "updated_at": now_local.isoformat(),
        "data": {},
    }


# 按订阅代码集合过滤市场快照内容。
def _filter_by_subscription(
    market_snapshot: dict[str, list[dict]],
    subscription_codes: dict[str, set[str]],
) -> dict[str, list[dict]]:
    return {
        market: [row for row in market_rows(market_snapshot, market) if quote_code(row) in allow_codes]
        for market, allow_codes in subscription_codes.items()
    }


# 根据标的元数据构造空白行情行。
def _build_null_quote_row(meta: dict) -> dict:
    short_code = resolve_short_code(meta.get("short_code"), meta.get("symbol"))
    return {
        "short_code": short_code,
        "name": str(meta.get("name") or ""),
        "logo_url": meta.get("logo_url") or None,
        "logo_color": meta.get("logo_color") or None,
        "prev_close": None,
        "day_high": None,
        "day_low": None,
        "price": None,
        "pct": None,
        "volume": None,
    }


# 将行情行与标的元数据合并。
def _row_with_meta(row: dict, meta: dict) -> dict:
    merged = dict(row)
    merged["short_code"] = normalize_code(merged.get("short_code")) or normalize_code(meta.get("short_code"))
    merged["name"] = merged.get("name") or str(meta.get("name") or "")
    merged["logo_url"] = meta.get("logo_url") or None
    merged["logo_color"] = meta.get("logo_color") or None
    return merged


# 将最新行情、旧缓存和空白占位合并为完整快照。
def _merge_with_fallback(
    previous_data: dict[str, list[dict]],
    latest_quotes: dict[str, list[dict]],
    watchlist_meta: dict[str, dict[str, dict]],
) -> tuple[dict[str, list[dict]], int, int]:
    merged: dict[str, list[dict]] = {}
    reused_previous = 0
    filled_null = 0
    markets = set(watchlist_meta.keys()) | set(previous_data.keys()) | set(latest_quotes.keys())

    for market in markets:
        expected_meta = watchlist_meta.get(market, {})
        prev_by_code = index_rows_by_code(market_rows(previous_data, market))
        new_by_code = index_rows_by_code(market_rows(latest_quotes, market))

        rows: list[dict] = []
        for code, meta in expected_meta.items():
            if code in new_by_code:
                rows.append(_row_with_meta(new_by_code[code], meta))
                continue
            if code in prev_by_code:
                rows.append(_row_with_meta(prev_by_code[code], meta))
                reused_previous += 1
                continue
            rows.append(_build_null_quote_row(meta))
            filled_null += 1

        merged[market] = rows

    return merged, reused_previous, filled_null


# 找出快照中仍然缺失的订阅代码。
def _missing_subscription_codes(
    snapshot: dict[str, list[dict]],
    subscription_codes: dict[str, set[str]],
) -> dict[str, set[str]]:
    missing: dict[str, set[str]] = {}
    for market, expected_codes in subscription_codes.items():
        actual_codes = snapshot_code_set(market_rows(snapshot, market))
        miss = expected_codes - actual_codes
        if miss:
            missing[market] = miss
    return missing


# 构建本次行情拉取所需的上下文数据。
def _build_context(now_local: datetime) -> _PullContext:
    previous_payload = get_market_data_payload()
    previous_data = safe_payload_data(previous_payload)
    subscription_meta = global_subscription_meta_by_market()
    subscription_codes = {market: set(meta.keys()) for market, meta in subscription_meta.items()}
    return _PullContext(
        now_local=now_local,
        previous_data=previous_data,
        subscription_meta=subscription_meta,
        subscription_codes=subscription_codes,
    )


# 根据上下文生成本次行情拉取计划。
def _build_plan(context: _PullContext) -> _PullPlan:
    due_markets, guard_decisions = resolve_due_markets(
        context.subscription_codes.keys(),
        now_utc=context.now_local.astimezone(dt_timezone.utc),
    )
    return _PullPlan(due_markets=due_markets, guard_decisions=guard_decisions)


# Celery 首次启动时强制拉取所有已订阅市场，避免仅因时段守卫而写入空占位。
def _build_force_bootstrap_plan(context: _PullContext) -> _PullPlan:
    due_markets = set(context.subscription_codes.keys())
    decisions = {
        market: GuardDecision(
            market=market,
            should_pull=True,
            reason="bootstrap_force",
            session="bootstrap",
        )
        for market in sorted(due_markets)
    }
    return _PullPlan(due_markets=due_markets, guard_decisions=decisions)


# 记录各市场的拉取守卫决策日志。
def _log_guard_decisions(guard_decisions: dict[str, GuardDecision]) -> None:
    for market, decision in sorted(guard_decisions.items()):
        event = "calendar.guard.due" if decision.should_pull else "calendar.guard.skip"
        log_info(
            logger,
            event,
            market=market,
            session=decision.session,
            reason=decision.reason,
        )


# 拉取当前计划中到期市场的行情数据。
def _fetch_due_quotes(plan: _PullPlan) -> dict[str, list[dict]]:
    _log_guard_decisions(plan.guard_decisions)
    if not plan.due_markets:
        return {}
    return pull_watchlist_quotes(allowed_markets=plan.due_markets)


# 批量拉取缺项时，首次初始化再逐条补拉一次，尽量避免空行情占位。
def _backfill_missing_quotes(
    *,
    latest_quotes: dict[str, list[dict]],
    subscription_meta: dict[str, dict[str, dict]],
) -> dict[str, list[dict]]:
    missing_before = _missing_subscription_codes(latest_quotes, {
        market: set(meta.keys()) for market, meta in subscription_meta.items()
    })
    if not missing_before:
        return latest_quotes

    recovered = 0
    remaining: dict[str, list[str]] = {}
    for market, codes in missing_before.items():
        for code in sorted(codes):
            meta = subscription_meta.get(market, {}).get(code, {})
            quote_row = pull_single_instrument_quote(
                symbol=str(meta.get("symbol") or ""),
                short_code=str(meta.get("short_code") or code),
                name=str(meta.get("name") or code),
                market=market,
            )
            if quote_row:
                latest_quotes.setdefault(market, []).append(quote_row)
                recovered += 1
            else:
                remaining.setdefault(market, []).append(code)

    if recovered or remaining:
        logger.warning(
            "启动初始化单条补拉 completed=%s remaining=%s",
            recovered,
            remaining,
        )
    return latest_quotes


# 组装最终要写入缓存的市场快照负载。
def _build_payload(
    context: _PullContext,
    merged_data: dict[str, list[dict]],
) -> dict:
    return {
        "updated_at": context.now_local.isoformat(),
        "data": merged_data,
    }


# 将市场快照及分市场缓存写入存储。
def _persist_market_snapshot(payload: dict, previous_data: dict[str, list[dict]]) -> None:
    cache.set(WATCHLIST_QUOTES_KEY, payload, timeout=None)
    removed_markets = set(previous_data.keys()) - set(payload["data"].keys())
    for market in removed_markets:
        cache.delete(instrument_market_cache_key(market))

    for market, market_quotes in payload["data"].items():
        market_key = instrument_market_cache_key(market)
        cache.set(
            market_key,
            {
                "updated_at": payload["updated_at"],
                "market": market,
                "data": market_quotes,
            },
            timeout=None,
        )


# 在发生回退补齐时输出告警日志。
def _warn_merge_result(*, reused_previous: int, filled_null: int) -> None:
    if reused_previous or filled_null:
        logger.warning("行情抓取回退生效 reused_previous=%s filled_null=%s", reused_previous, filled_null)


# 在快照仍有缺口时输出告警日志。
def _warn_missing_quotes(
    *,
    snapshot: dict[str, list[dict]],
    subscription_codes: dict[str, set[str]],
    previous_data: dict[str, list[dict]],
    quotes: dict[str, list[dict]],
) -> None:
    missing_after = _missing_subscription_codes(snapshot, subscription_codes)
    if missing_after:
        logger.warning("行情补齐后仍有缺口 missing=%s", {k: sorted(v) for k, v in missing_after.items()})
    elif not previous_data and quotes:
        logger.warning("首次任务启动，已执行全市场初始化拉取")


# 执行一次完整的自选市场行情同步。
def refresh_watchlist(*, now_local: datetime | None = None, force_full_fetch: bool = False) -> dict:
    current_time = now_local or timezone.now().astimezone(UTC8)
    context = _build_context(current_time)
    if not (context.subscription_codes or context.previous_data):
        payload = _empty_market_payload(current_time)
        log_info(logger, "watchlist.snapshot.skip_sync", reason="no_subscription_and_no_cache")
        return payload

    plan = _build_force_bootstrap_plan(context) if force_full_fetch else _build_plan(context)
    latest_quotes = _fetch_due_quotes(plan)
    if force_full_fetch:
        latest_quotes = _backfill_missing_quotes(
            latest_quotes=latest_quotes,
            subscription_meta=context.subscription_meta,
        )
    merged_data, reused_previous, filled_null = _merge_with_fallback(
        context.previous_data,
        latest_quotes,
        context.subscription_meta,
    )
    merged_data = _filter_by_subscription(merged_data, context.subscription_codes)
    _warn_merge_result(reused_previous=reused_previous, filled_null=filled_null)
    _warn_missing_quotes(
        snapshot=merged_data,
        subscription_codes=context.subscription_codes,
        previous_data=context.previous_data,
        quotes=latest_quotes,
    )

    payload = _build_payload(context, merged_data)

    try:
        _persist_market_snapshot(payload, context.previous_data)
    except Exception:
        logger.exception("写入自选行情到 Redis 失败")

    if not latest_quotes and context.previous_data:
        log_info(logger, "watchlist.snapshot.no_market_update")

    return payload
