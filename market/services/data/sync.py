from __future__ import annotations

from django.utils import timezone

from .cache import UTC8
from .indices import pull_indices
from .market import pull_market
from .usd_baserate import pull_usd_base_rate


def pull_data() -> dict:
    now_local = timezone.now().astimezone(UTC8)
    market_data = pull_market(now_local=now_local)
    indices_data = pull_indices(now_local=now_local)
    usd_baserate_data = pull_usd_base_rate(now_local=now_local, market_data=market_data)
    return {
        "market_data": market_data,
        "indices_data": indices_data,
        "usd_baserate_data": usd_baserate_data,
    }
