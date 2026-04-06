from __future__ import annotations

from django.contrib.auth import get_user_model

from investment.services.query_service import get_recent_trades as query_recent_trades


def get_recent_trades(*, user_id: int, symbols: list[str] | None = None, limit: int | None = None) -> dict:
    user = get_user_model().objects.get(id=user_id)
    return query_recent_trades(user=user, symbols=symbols, limit=limit)
