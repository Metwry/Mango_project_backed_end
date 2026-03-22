from django.core.cache import cache

from common.utils import normalize_usd_rates

from .cache import USD_EXCHANGE_RATES_KEY
from .usd_baserate import pull_usd_base_rate


def _normalize_rates(raw_rates: object) -> dict[str, float]:
    return {code: float(value) for code, value in normalize_usd_rates(raw_rates).items()}


def get_fx_rates(requested_base: str) -> dict:
    base = str(requested_base or "USD").strip().upper()

    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    rates = _normalize_rates(payload.get("rates") if isinstance(payload, dict) else None)
    updated_at = payload.get("updated_at") if isinstance(payload, dict) else None

    if len(rates) <= 1:
        pull_usd_base_rate()
        payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
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
