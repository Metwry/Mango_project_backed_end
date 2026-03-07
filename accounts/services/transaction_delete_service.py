from decimal import Decimal

from django.db import transaction as db_transaction
from rest_framework.exceptions import NotFound, ValidationError

from accounts.models import Accounts, Transaction
from investment.models import InvestmentRecord

from .currency_service import convert_amount_or_raise
from .transaction_query_service import (
    ACTIVITY_INVESTMENT,
    ACTIVITY_MANUAL,
    ACTIVITY_REVERSED,
)


def _lock_original_transaction_or_raise(*, user, tx_id: int) -> Transaction:
    tx = (
        Transaction.objects
        .select_for_update()
        .filter(pk=tx_id, user=user)
        .first()
    )
    if tx is None:
        raise NotFound("交易不存在或无权限。")
    if tx.reversal_of_id is not None:
        raise ValidationError({"transaction_id": "不支持直接删除冲正流水，请删除对应原交易。"})
    return tx


def _build_original_queryset_by_activity(*, user, activity_type: str):
    queryset = (
        Transaction.objects
        .select_for_update()
        .filter(user=user, reversal_of__isnull=True)
        .order_by("-add_date", "-id")
    )
    if activity_type == ACTIVITY_INVESTMENT:
        return queryset.filter(source=Transaction.Source.INVESTMENT, reversed_at__isnull=True)
    if activity_type == ACTIVITY_REVERSED:
        return queryset.filter(reversed_at__isnull=False)
    return queryset.filter(source=Transaction.Source.MANUAL, reversed_at__isnull=True)


def _collect_rows_for_deletion(*, originals: list[Transaction]) -> tuple[list[Transaction], list[Transaction]]:
    if not originals:
        return [], []

    original_ids = [tx.id for tx in originals]
    reversal_rows = list(
        Transaction.objects
        .select_for_update()
        .filter(reversal_of_id__in=original_ids)
    )
    all_rows_map = {tx.id: tx for tx in originals}
    for row in reversal_rows:
        all_rows_map[row.id] = row
    return originals, list(all_rows_map.values())


def _revert_account_balances(*, rows: list[Transaction]) -> None:
    account_map: dict[int, Accounts] = {}
    for row in rows:
        account = account_map.get(row.account_id)
        if account is None:
            account = Accounts.objects.select_for_update().get(pk=row.account_id)
            account_map[row.account_id] = account
        try:
            rollback_amount = convert_amount_or_raise(
                amount=row.amount or Decimal("0"),
                from_currency=row.currency,
                to_currency=account.currency,
            )
        except ValueError as exc:
            raise ValidationError({"message": str(exc)})
        account.balance = (account.balance or Decimal("0")) - rollback_amount

    for account in account_map.values():
        account.save(update_fields=["balance", "updated_at"])


def _delete_rows(*, user, rows: list[Transaction]) -> int:
    if not rows:
        return 0
    ids = [row.id for row in rows]
    InvestmentRecord.objects.filter(user=user, cash_transaction_id__in=ids).update(cash_transaction=None)
    _revert_account_balances(rows=rows)
    reversal_ids = [row.id for row in rows if row.reversal_of_id is not None]
    original_ids = [row.id for row in rows if row.reversal_of_id is None]
    if reversal_ids:
        Transaction.objects.filter(user=user, id__in=reversal_ids).delete()
    if original_ids:
        Transaction.objects.filter(user=user, id__in=original_ids).delete()
    return len(ids)


def delete_single_transaction(*, user, tx_id: int) -> dict:
    with db_transaction.atomic():
        original = _lock_original_transaction_or_raise(user=user, tx_id=tx_id)
        originals, rows = _collect_rows_for_deletion(originals=[original])
        deleted_rows = _delete_rows(user=user, rows=rows)
        return {
            "mode": "single",
            "activity_type": original.source,
            "visible_deleted": len(originals),
            "transaction_rows_deleted": deleted_rows,
        }


def delete_transactions_by_activity(*, user, activity_type: str) -> dict:
    with db_transaction.atomic():
        originals = list(_build_original_queryset_by_activity(user=user, activity_type=activity_type))
        original_count = len(originals)
        _, rows = _collect_rows_for_deletion(originals=originals)
        deleted_rows = _delete_rows(user=user, rows=rows)
        return {
            "mode": "activity",
            "activity_type": activity_type,
            "visible_deleted": original_count,
            "transaction_rows_deleted": deleted_rows,
        }
