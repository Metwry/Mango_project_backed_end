from decimal import Decimal

from django.core.cache import cache

from common.utils import normalize_code, normalize_usd_rates, quantize_decimal
from market.services.data.cache import USD_EXCHANGE_RATES_KEY

ACCOUNT_PRECISION = Decimal("0.01")


# ed 从缓存中读取并标准化美元基准汇率表。
def load_cached_usd_rates() -> dict[str, Decimal]:
    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    raw_rates = payload.get("rates") if isinstance(payload, dict) else {}
    return normalize_usd_rates(raw_rates)


# 按缓存汇率将金额从源币种转换到目标币种，缺少汇率时抛出异常。
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

