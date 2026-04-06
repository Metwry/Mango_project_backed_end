from __future__ import annotations

from accounts.models import Accounts, Transaction


def _normalize_account_ids(account_ids: list[int] | list[str] | None) -> list[int] | None:
    if account_ids is None:
        return None
    normalized: list[int] = []
    seen: set[int] = set()
    for account_id in account_ids:
        value = int(account_id)
        if value in seen:
            continue
        seen.add(value)
        normalized.append(value)
    return normalized


def get_account_summary(*, user) -> dict:
    queryset = (
        Accounts.objects
        .filter(user=user)
        .order_by("-balance", "-updated_at")
    )

    return {
        "accounts": [
            {
                "account_id": str(account.id),
                "name": account.name,
                "type": account.type,
                "currency": account.currency,
                "balance": str(account.balance),
                "status": account.status,
            }
            for account in queryset
        ]
    }


def get_recent_transaction(*, user, account_ids: list[int] | list[str] | None = None,
                           limit: int | None = None) -> dict:
    normalized_account_ids = _normalize_account_ids(account_ids)
    effective_limit = int(limit or 10)

    queryset = (
        Transaction.objects
        .select_related("account", "transfer_account")
        .filter(user=user)
        .order_by("-add_date", "-id")
    )
    if normalized_account_ids is not None:
        queryset = queryset.filter(account_id__in=normalized_account_ids)

    rows = list(queryset[:effective_limit])
    return {
        "count": str(len(rows)),
        "items": [
            {
                "id": str(row.id),
                "account_id": str(row.account_id),
                "account_name": row.account.name,
                "type": row.source,
                "amount": str(row.amount),
                "currency": row.currency,
                "occurred_at": row.add_date.isoformat(),
                "counterparty": row.counterparty,
                "category_name": row.category_name,
                "remark": row.remark,
                "transfer_account_id": str(row.transfer_account_id) if row.transfer_account_id else None,
                "transfer_account_name": row.transfer_account.name if row.transfer_account_id else None,
            }
            for row in rows
        ],
    }
