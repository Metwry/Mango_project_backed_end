from __future__ import annotations

from django.contrib.auth import get_user_model

from accounts.services import get_recent_transaction as query_recent_transaction


def get_recent_transaction(
    *,
    user_id: int,
    account_ids: list[int] | list[str] | None = None,
    limit: int | None = None,
) -> dict:
    user = get_user_model().objects.get(id=user_id)
    return query_recent_transaction(user=user, account_ids=account_ids, limit=limit)
