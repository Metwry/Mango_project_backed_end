from __future__ import annotations

from django.contrib.auth import get_user_model

from accounts.services import get_account_summary as query_account_summary


def get_account_summary(*, user_id: int) -> dict:
    user = get_user_model().objects.get(id=user_id)
    return query_account_summary(user=user)
