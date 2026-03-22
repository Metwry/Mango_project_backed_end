from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone as dt_timezone

from django.core.cache import cache
from django.utils import timezone

from common.logging_utils import log_info
from common.utils import normalize_code, resolve_short_code, safe_payload_data

from ..subscription.service import global_subscription_meta_by_market
from .cache import UTC8, WATCHLIST_QUOTES_KEY, WATCHLIST_QUOTES_MARKET_KEY_PREFIX
from .pull_guard import GuardDecision, resolve_due_markets
from .quote_rows import index_rows_by_code, market_rows, quote_code, snapshot_code_set

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


def pull_watchlist_quotes(*args, **kwargs):
    from accounts.services.quote_fetcher import pull_watchlist_quotes as impl

    return impl(*args, **kwargs)


def _filter_by_subscription(
    market_snapshot: dict[str, list[dict]],
    subscription_codes: dict[str, set[str]],
) -> dict[str, list[dict]]:
    return {
        market: [row for row in market_rows(market_snapshot, market) if quote_code(row) in allow_codes]
        for market, allow_codes in subscription_codes.items()
    }


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


def _row_with_meta(row: dict, meta: dict) -> dict:
    merged = dict(row)
    merged["short_code"] = normalize_code(merged.get("short_code")) or normalize_code(meta.get("short_code"))
    merged["name"] = merged.get("name") or str(meta.get("name") or "")
    merged["logo_url"] = meta.get("logo_url") or None
    merged["logo_color"] = meta.get("logo_color") or None
    return merged


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


def _build_context(now_local: datetime) -> _PullContext:
    previous_payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
    previous_data = safe_payload_data(previous_payload)
    subscription_meta = global_subscription_meta_by_market()
    subscription_codes = {market: set(meta.keys()) for market, meta in subscription_meta.items()}
    return _PullContext(
        now_local=now_local,
        previous_data=previous_data,
        subscription_meta=subscription_meta,
        subscription_codes=subscription_codes,
    )


def _build_plan(context: _PullContext) -> _PullPlan:
    due_markets, guard_decisions = resolve_due_markets(
        context.subscription_codes.keys(),
        now_utc=context.now_local.astimezone(dt_timezone.utc),
    )
    return _PullPlan(
        due_markets=due_markets,
        guard_decisions=guard_decisions,
    )


def _log_guard_decisions(guard_decisions: dict[str, GuardDecision]) -> None:
    for market, decision in sorted(guard_decisions.items()):
        if decision.should_pull:
            log_info(
                logger,
                "calendar.guard.due",
                market=market,
                session=decision.session,
                reason=decision.reason,
            )
        else:
            log_info(
                logger,
                "calendar.guard.skip",
                market=market,
                session=decision.session,
                reason=decision.reason,
            )


def _pull_due_markets(plan: _PullPlan) -> dict[str, list[dict]]:
    _log_guard_decisions(plan.guard_decisions)

    if plan.due_markets:
        return pull_watchlist_quotes(
            force_fetch_all_markets=False,
            allowed_markets=plan.due_markets,
        )
    return {}


def _build_payload(
    context: _PullContext,
    merged_data: dict[str, list[dict]],
    quotes: dict[str, list[dict]],
    due_markets: set[str],
) -> dict:
    updated_markets = set(quotes.keys())
    stale_markets = sorted(set(merged_data.keys()) - updated_markets)
    return {
        "updated_at": context.now_local.isoformat(),
        "bootstrap_mode": not context.previous_data,
        "updated_markets": sorted(updated_markets),
        "stale_markets": stale_markets,
        "guard_due_markets": sorted(due_markets),
        "data": merged_data,
    }


def _write_market_cache(payload: dict, previous_data: dict[str, list[dict]]) -> None:
    cache.set(WATCHLIST_QUOTES_KEY, payload, timeout=None)
    removed_markets = set(previous_data.keys()) - set(payload["data"].keys())
    for market in removed_markets:
        cache.delete(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}")

    updated_markets = set(payload["updated_markets"])
    stale_markets = set(payload["stale_markets"])
    for market, market_quotes in payload["data"].items():
        market_key = f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}"
        existing_market_payload = cache.get(market_key)
        existing_pulled_at = existing_market_payload.get("pulled_at") if isinstance(existing_market_payload, dict) else None
        pulled_at = payload["updated_at"] if market in updated_markets else existing_pulled_at
        cache.set(
            market_key,
            {
                "updated_at": payload["updated_at"],
                "pulled_at": pulled_at,
                "market": market,
                "stale": market in stale_markets,
                "data": market_quotes,
            },
            timeout=None,
        )


def _sync_investment_account_balances() -> None:
    from investment.models import Position
    from investment.services.account_service import sync_investment_accounts_for_users

    active_position_user_ids = (
        Position.objects
        .filter(quantity__gt=0)
        .values_list("user_id", flat=True)
        .distinct()
    )
    sync_result = sync_investment_accounts_for_users(user_ids=active_position_user_ids)
    failed_user_ids = sync_result.get("failed_user_ids") or []
    if failed_user_ids:
        logger.warning("投资账户余额同步部分失败 failed_user_ids=%s", failed_user_ids)


def pull_market(*, now_local: datetime | None = None) -> dict:
    current_time = now_local or timezone.now().astimezone(UTC8)
    context = _build_context(current_time)
    if not (context.subscription_codes or context.previous_data):
        payload = {
            "updated_at": current_time.isoformat(),
            "bootstrap_mode": False,
            "updated_markets": [],
            "stale_markets": [],
            "guard_due_markets": [],
            "data": {},
        }
        log_info(logger, "watchlist.snapshot.skip_sync", reason="no_subscription_and_no_cache")
        return payload

    plan = _build_plan(context)
    quotes = _pull_due_markets(plan)
    merged_data, reused_previous, filled_null = _merge_with_fallback(
        context.previous_data,
        quotes,
        context.subscription_meta,
    )
    merged_data = _filter_by_subscription(merged_data, context.subscription_codes)
    if reused_previous or filled_null:
        logger.warning("行情抓取回退生效 reused_previous=%s filled_null=%s", reused_previous, filled_null)

    missing_after = _missing_subscription_codes(merged_data, context.subscription_codes)
    if missing_after:
        logger.warning("行情补齐后仍有缺口 missing=%s", {k: sorted(v) for k, v in missing_after.items()})
    elif not context.previous_data and quotes:
        logger.warning("首次任务启动，已执行全市场初始化拉取")

    payload = _build_payload(context, merged_data, quotes, plan.due_markets)

    try:
        _write_market_cache(payload, context.previous_data)
    except Exception:
        logger.exception("写入自选行情到 Redis 失败")

    try:
        _sync_investment_account_balances()
    except Exception:
        logger.exception("同步投资账户余额失败")

    if not quotes and context.previous_data:
        log_info(logger, "watchlist.snapshot.no_market_update", stale_markets=payload["stale_markets"])

    return payload
