from __future__ import annotations

from django.contrib.auth import get_user_model

from snapshot.services.query_service import get_position_trend as query_position_trend


def get_position_trend(*, user_id: int, start: str | None = None, end: str | None = None,
                       symbols: list[str] | None = None, fields: list[str] | None = None) -> dict:
    user = get_user_model().objects.get(id=user_id)
    return query_position_trend(
        user=user,
        start=start,
        end=end,
        symbols=symbols,
        fields=fields,
    )
