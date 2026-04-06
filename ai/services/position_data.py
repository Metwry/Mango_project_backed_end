from __future__ import annotations

from django.contrib.auth import get_user_model

from investment.services.query_service import get_position_data as query_position_data


def get_position_data(*, user_id: int, symbols: list[str] | None = None) -> dict:
    user = get_user_model().objects.get(id=user_id)
    return query_position_data(user=user, symbols=symbols)
