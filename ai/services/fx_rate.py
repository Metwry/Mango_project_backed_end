from __future__ import annotations

from market.services.pricing import get_usd_base_fx_snapshot


def get_fx_rate() -> dict:
    return get_usd_base_fx_snapshot()
