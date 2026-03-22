from __future__ import annotations

import logging
from datetime import datetime

from django.core.cache import cache
from django.utils import timezone

from common.logging_utils import log_info
from common.utils import normalize_code, safe_payload_data

from .cache import FX_REFRESH_INTERVAL, USD_EXCHANGE_RATES_KEY, UTC8, WATCHLIST_QUOTES_KEY

logger = logging.getLogger(__name__)


def pull_usd_exchange_rates(*args, **kwargs):
    from accounts.services.quote_fetcher import pull_usd_exchange_rates as impl

    return impl(*args, **kwargs)


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


def _need_refresh_usd_base_rate(now_local: datetime) -> bool:
    from accounts.services.quote_fetcher import USD_MAINSTREAM_CURRENCIES

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


def _extract_fx_rows(market_data: dict | None) -> list[dict]:
    payload = market_data if isinstance(market_data, dict) else (cache.get(WATCHLIST_QUOTES_KEY) or {})
    fx_rows = safe_payload_data(payload).get("FX", [])
    return fx_rows if isinstance(fx_rows, list) else []


def pull_usd_base_rate(*, now_local: datetime | None = None, market_data: dict | None = None) -> dict:
    current_time = now_local or timezone.now().astimezone(UTC8)
    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    existing_rates = payload.get("rates") if isinstance(payload, dict) else {}
    existing_count = len(existing_rates) if isinstance(existing_rates, dict) else 0

    if not _need_refresh_usd_base_rate(current_time):
        log_info(logger, "fx.usd_snapshot.skip_refresh", reason="refresh_interval_not_reached")
        return {
            "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
            "base": "USD",
            "rates_count": existing_count,
            "refreshed": False,
        }

    fx_rows = _extract_fx_rows(market_data)
    usd_rates = pull_usd_exchange_rates(seed_rows=fx_rows)
    updated_at = current_time.isoformat()
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
    return {
        "updated_at": updated_at,
        "base": "USD",
        "rates_count": len(usd_rates),
        "refreshed": True,
    }
