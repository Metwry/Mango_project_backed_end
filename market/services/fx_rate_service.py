from django.core.cache import cache
from django.utils import timezone

from accounts.services import pull_usd_exchange_rates
from shared.fx import normalize_usd_rates

from .cache_keys import USD_EXCHANGE_RATES_KEY, UTC8, WATCHLIST_QUOTES_KEY


def _normalize_rates(raw_rates: object) -> dict[str, float]:
    return {code: float(value) for code, value in normalize_usd_rates(raw_rates).items()}


def get_fx_rates(requested_base: str) -> dict:
    base = str(requested_base or "USD").strip().upper()

    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    rates = _normalize_rates(payload.get("rates") if isinstance(payload, dict) else None)
    updated_at = payload.get("updated_at") if isinstance(payload, dict) else None

    if len(rates) <= 1:
        watch_payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
        snapshot_data = watch_payload.get("data") if isinstance(watch_payload, dict) else {}
        fx_rows = snapshot_data.get("FX") if isinstance(snapshot_data, dict) else []
        if not isinstance(fx_rows, list):
            fx_rows = []

        rates = pull_usd_exchange_rates(seed_rows=fx_rows)
        updated_at = timezone.now().astimezone(UTC8).isoformat()
        cache.set(
            USD_EXCHANGE_RATES_KEY,
            {"base": "USD", "updated_at": updated_at, "rates": rates},
            timeout=None,
        )

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
