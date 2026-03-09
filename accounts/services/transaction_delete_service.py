from django.db import transaction as db_transaction
from rest_framework.exceptions import NotFound, ValidationError

from accounts.models import Transaction
from investment.models import InvestmentRecord
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
    if tx.source == Transaction.Source.TRANSFER:
        raise ValidationError({"transaction_id": "转账流水不允许删除，请使用撤销功能。"})
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


def _assert_no_transfer_rows(*, originals: list[Transaction]) -> None:
    if any(row.source == Transaction.Source.TRANSFER for row in originals):
        raise ValidationError({"message": "转账流水不允许删除，请使用撤销功能。"})

def _delete_rows(*, user, rows: list[Transaction]) -> int:
    if not rows:
        return 0
    ids = [row.id for row in rows]
    InvestmentRecord.objects.filter(user=user, cash_transaction_id__in=ids).update(cash_transaction=None)
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
        _assert_no_transfer_rows(originals=originals)
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
        _assert_no_transfer_rows(originals=originals)
        _, rows = _collect_rows_for_deletion(originals=originals)
        deleted_rows = _delete_rows(user=user, rows=rows)
        return {
            "mode": "activity",
            "activity_type": activity_type,
            "visible_deleted": original_count,
            "transaction_rows_deleted": deleted_rows,
        }
