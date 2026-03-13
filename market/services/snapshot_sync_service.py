import logging
from datetime import datetime
from typing import Dict, List, Set

from django.core.cache import cache
from django.utils import timezone

from accounts.services import (
    USD_MAINSTREAM_CURRENCIES,
    pull_usd_exchange_rates,
    pull_watchlist_quotes,
)
from shared.logging_utils import log_info
from shared.utils import normalize_code, resolve_short_code, safe_payload_data

from .cache_keys import (
    FX_REFRESH_INTERVAL,
    USD_EXCHANGE_RATES_KEY,
    UTC8,
    WATCHLIST_QUOTES_KEY,
    WATCHLIST_QUOTES_MARKET_KEY_PREFIX,
)
from .calendar_guard_service import resolve_due_markets
from .subscription_query_service import global_subscription_meta_by_market

logger = logging.getLogger(__name__)

def _filter_snapshot_by_subscription(
    snapshot: Dict[str, List[dict]],
    subscription_codes: Dict[str, Set[str]],
) -> Dict[str, List[dict]]:
    filtered: Dict[str, List[dict]] = {}
    for market, allow_codes in subscription_codes.items():
        market_quotes = snapshot.get(market, [])
        if not isinstance(market_quotes, list):
            filtered[market] = []
            continue
        kept = []
        for row in market_quotes:
            if not isinstance(row, dict):
                continue
            code = resolve_short_code(row.get("short_code"), row.get("symbol"))
            if code in allow_codes:
                kept.append(row)
        filtered[market] = kept
    return filtered


def _snapshot_code_set(rows: object) -> Set[str]:
    codes: Set[str] = set()
    if not isinstance(rows, list):
        return codes
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = resolve_short_code(row.get("short_code"), row.get("symbol"))
        if code:
            codes.add(code)
    return codes


def _index_rows_by_code(rows: object) -> Dict[str, dict]:
    out: Dict[str, dict] = {}
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        code = resolve_short_code(row.get("short_code"), row.get("symbol"))
        if code:
            out[code] = row
    return out


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


def _merge_snapshot_with_fallback(
    previous_data: Dict[str, List[dict]],
    latest_quotes: Dict[str, List[dict]],
    watchlist_meta: Dict[str, Dict[str, dict]],
) -> tuple[Dict[str, List[dict]], int, int]:
    merged: Dict[str, List[dict]] = {}
    reused_previous = 0
    filled_null = 0
    markets = set(watchlist_meta.keys()) | set(previous_data.keys()) | set(latest_quotes.keys())

    for market in markets:
        expected_meta = watchlist_meta.get(market, {})
        prev_by_code = _index_rows_by_code(previous_data.get(market, []))
        new_rows = latest_quotes.get(market)
        new_by_code = _index_rows_by_code(new_rows) if isinstance(new_rows, list) else {}

        rows: List[dict] = []
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
    snapshot: Dict[str, List[dict]],
    subscription_codes: Dict[str, Set[str]],
) -> Dict[str, Set[str]]:
    missing: Dict[str, Set[str]] = {}
    for market, expected_codes in subscription_codes.items():
        actual_codes = _snapshot_code_set(snapshot.get(market, []))
        miss = expected_codes - actual_codes
        if miss:
            missing[market] = miss
    return missing


def _parse_iso_datetime(raw: object) -> datetime | None:
    if not isinstance(raw, str) or not raw.strip():
        return None
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    if dt.tzinfo is None:
        return timezone.make_aware(dt, UTC8)
    return dt


def _need_refresh_fx_rates(now_local: datetime) -> bool:
    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    if not isinstance(payload, dict):
        return True
    rates = payload.get("rates")
    if not isinstance(rates, dict):
        return True

    required = {"USD", *USD_MAINSTREAM_CURRENCIES}
    has_codes = {normalize_code(k) for k in rates.keys()}
    if not required.issubset(has_codes):
        return True

    last_updated = _parse_iso_datetime(payload.get("updated_at"))
    if last_updated is None:
        return True

    return now_local - last_updated.astimezone(UTC8) >= FX_REFRESH_INTERVAL


def sync_watchlist_snapshot() -> dict:
    now_local = timezone.now().astimezone(UTC8)
    previous_payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
    previous_data = safe_payload_data(previous_payload)
    subscription_meta = global_subscription_meta_by_market()
    subscription_codes = {m: set(meta.keys()) for m, meta in subscription_meta.items()}
    missing_before = _missing_subscription_codes(previous_data, subscription_codes)
    need_bootstrap = not previous_data
    need_repair = bool(missing_before)
    force_fetch_all = need_bootstrap or need_repair

    due_markets, guard_decisions = resolve_due_markets(subscription_codes.keys())
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

    if due_markets:
        quotes = pull_watchlist_quotes(
            force_fetch_all_markets=False,
            allowed_markets=due_markets,
        )
    else:
        if force_fetch_all:
            # Cold start / repair path: initialize once immediately instead of waiting
            # for the next due slot.
            force_markets = set(subscription_codes.keys()) if need_bootstrap else set(missing_before.keys())
            if force_markets:
                log_info(
                    logger,
                    "calendar.guard.force_init_pull",
                    need_bootstrap=need_bootstrap,
                    need_repair=need_repair,
                    force_markets=sorted(force_markets),
                )
                quotes = pull_watchlist_quotes(
                    force_fetch_all_markets=True,
                    allowed_markets=force_markets,
                )
            else:
                quotes = {}
                log_info(
                    logger,
                    "calendar.guard.block_bootstrap_or_repair",
                    need_bootstrap=need_bootstrap,
                    need_repair=need_repair,
                )
        else:
            quotes = {}
    merged_data, reused_previous, filled_null = _merge_snapshot_with_fallback(previous_data, quotes, subscription_meta)
    merged_data = _filter_snapshot_by_subscription(merged_data, subscription_codes)
    if reused_previous or filled_null:
        logger.warning("行情抓取回退生效 reused_previous=%s filled_null=%s", reused_previous, filled_null)

    missing_after = _missing_subscription_codes(merged_data, subscription_codes)
    if missing_after:
        logger.warning("行情补齐后仍有缺口 missing=%s", {k: sorted(v) for k, v in missing_after.items()})
    elif need_repair:
        logger.warning("检测到行情缺失并已补齐 missing_before=%s", {k: sorted(v) for k, v in missing_before.items()})
    elif need_bootstrap:
        logger.warning("首次任务启动，已执行全市场初始化拉取")

    updated_markets = set(quotes.keys())
    stale_markets = sorted(set(merged_data.keys()) - updated_markets)
    updated_at = now_local.isoformat()
    payload = {
        "updated_at": updated_at,
        "bootstrap_mode": need_bootstrap,
        "updated_markets": sorted(updated_markets),
        "stale_markets": stale_markets,
        "guard_due_markets": sorted(due_markets),
        "data": merged_data,
    }

    try:
        cache.set(WATCHLIST_QUOTES_KEY, payload, timeout=None)
        removed_markets = set(previous_data.keys()) - set(merged_data.keys())
        for market in removed_markets:
            cache.delete(f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}")
        for market, market_quotes in merged_data.items():
            market_key = f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}"
            existing_market_payload = cache.get(market_key)
            existing_pulled_at = (
                existing_market_payload.get("pulled_at")
                if isinstance(existing_market_payload, dict)
                else None
            )
            pulled_at = updated_at if market in updated_markets else existing_pulled_at
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
    except Exception:
        logger.exception("写入自选行情到 Redis 失败")

    try:
        fx_rows = merged_data.get("FX", [])
        if not isinstance(fx_rows, list):
            fx_rows = []
        if _need_refresh_fx_rates(now_local):
            usd_rates = pull_usd_exchange_rates(seed_rows=fx_rows)
            cache.set(
                USD_EXCHANGE_RATES_KEY,
                {
                    "base": "USD",
                    "updated_at": updated_at,
                    "rates": usd_rates,
                },
                timeout=None,
            )
            logger.warning("已刷新美元汇率快照（4小时周期或数据缺失触发）")
        else:
            log_info(logger, "fx.usd_snapshot.skip_refresh", reason="refresh_interval_not_reached")
    except Exception:
        logger.exception("写入美元汇率到 Redis 失败")

    try:
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
    except Exception:
        logger.exception("同步投资账户余额失败")

    if not quotes and previous_data:
        log_info(logger, "watchlist.snapshot.no_market_update", stale_markets=stale_markets)

    return payload
