from decimal import Decimal

from django.core.cache import cache

from market.services.cache_keys import USD_EXCHANGE_RATES_KEY
from shared.fx import normalize_usd_rates
from shared.utils import normalize_code, quantize_decimal

ACCOUNT_PRECISION = Decimal("0.01")


def load_cached_usd_rates() -> dict[str, Decimal]:
    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    raw_rates = payload.get("rates") if isinstance(payload, dict) else {}
    return normalize_usd_rates(raw_rates)


def convert_amount_or_raise(*, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    source = normalize_code(from_currency)
    target = normalize_code(to_currency)
    if not source or not target or source == target:
        return quantize_decimal(amount, ACCOUNT_PRECISION)

    rates = load_cached_usd_rates()
    source_rate = rates.get(source)
    target_rate = rates.get(target)
    if source_rate is None or target_rate is None or source_rate <= 0 or target_rate <= 0:
        raise ValueError(f"缺少汇率对数据：{source}/{target}，请先刷新汇率后重试。")

    converted = (amount / source_rate) * target_rate
    return quantize_decimal(converted, ACCOUNT_PRECISION)
