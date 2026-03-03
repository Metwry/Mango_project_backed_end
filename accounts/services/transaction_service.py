from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Transaction


def reverse_transaction(*, user, tx_id: int) -> Transaction:
    with db_transaction.atomic():
        tx = (
            Transaction.objects
            .select_for_update()
            .select_related("account")
            .get(pk=tx_id, user=user)
        )

        if tx.reversal_of_id is not None:
            raise ValidationError("撤销交易不能再次撤销。")
        if tx.reversed_at is not None:
            raise ValidationError("该交易已撤销，不能重复撤销。")

        reverse_tx = Transaction.objects.create(
            user=user,
            account=tx.account,
            counterparty=f"撤销: {tx.counterparty}",
            category_name="撤销",
            amount=Decimal("0") - (tx.amount or Decimal("0")),
            add_date=timezone.now(),
            reversal_of=tx,
        )

        tx.reversed_at = timezone.now()
        tx.save(update_fields=["reversed_at"])
        return reverse_tx
