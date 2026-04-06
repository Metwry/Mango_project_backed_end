from __future__ import annotations

from django.contrib.auth import get_user_model

from snapshot.services.query_service import get_account_trend as query_account_trend


def get_account_trend(
    *,
    user_id: int,
    start: str | None = None,
    end: str | None = None,
    account_ids: list[int] | list[str] | None = None,
    fields: list[str] | None = None,
) -> dict:
    user = get_user_model().objects.get(id=user_id)
    return query_account_trend(
        user=user,
        start=start,
        end=end,
        account_ids=account_ids,
        fields=fields,
    )
