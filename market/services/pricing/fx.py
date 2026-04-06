from decimal import Decimal

from common.normalize import normalize_code, normalize_usd_rates
from common.utils import format_decimal_str, quantize_decimal

from .cache import get_usd_rate_payload
from ..refresh.usd_rates import refresh_usd_rates

ACCOUNT_PRECISION = Decimal("0.01")


# 从缓存读取并标准化美元基准汇率表。
def load_cached_usd_rates() -> dict[str, Decimal]:
    payload = get_usd_rate_payload()
    raw_rates = payload.get("rates") if isinstance(payload, dict) else {}
    return normalize_usd_rates(raw_rates)


def get_usd_base_fx_snapshot() -> dict:
    payload = get_usd_rate_payload()
    rates = payload.get("rates") if isinstance(payload, dict) else {}
    normalized_rates = normalize_usd_rates(rates)

    if len(normalized_rates) <= 1:
        refresh_usd_rates()
        payload = get_usd_rate_payload()
        rates = payload.get("rates") if isinstance(payload, dict) else {}
        normalized_rates = normalize_usd_rates(rates)

    return {
        "base": "USD",
        "updated_at": payload.get("updated_at") if isinstance(payload, dict) else None,
        "rates": {
            code: format_decimal_str(value)
            for code, value in normalized_rates.items()
        },
    }


# 按美元基准汇率将金额从一种货币换算到另一种货币。
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


# 将缓存里的汇率值统一转换为浮点数字典。
def _normalize_rates(raw_rates: object) -> dict[str, float]:
    return {code: float(value) for code, value in normalize_usd_rates(raw_rates).items()}


# 返回指定基准货币下的汇率快照。
def get_fx_rates(requested_base: str) -> dict:
    base = str(requested_base or "USD").strip().upper()

    payload = get_usd_rate_payload()
    rates = _normalize_rates(payload.get("rates") if isinstance(payload, dict) else None)
    updated_at = payload.get("updated_at") if isinstance(payload, dict) else None

    if len(rates) <= 1:
        refresh_usd_rates()
        payload = get_usd_rate_payload()
        rates = _normalize_rates(payload.get("rates") if isinstance(payload, dict) else None)
        updated_at = payload.get("updated_at") if isinstance(payload, dict) else None

    if base not in rates:
        raise ValueError(f"unsupported base currency: {base}")

    if base == "USD":
        final_rates = rates
    else:
        base_usd_rate = rates[base]
        final_rates = {code: (usd_rate / base_usd_rate) for code, usd_rate in rates.items()}
        final_rates[base] = 1.0

    return {
        "base": base,
        "updated_at": updated_at,
        "rates": final_rates,
    }
