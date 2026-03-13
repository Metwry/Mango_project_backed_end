from decimal import Decimal

from django.db import transaction as db_transaction
from django.db.models import Q
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from accounts.models import Accounts, Transaction, Transfer, is_system_investment_account

TRANSFER_CATEGORY = "转账"
TRANSFER_OUT_REMARK = "转出"
TRANSFER_IN_REMARK = "转入"


def _lock_account_for_transfer(*, user, account_id: int, field_name: str) -> Accounts:
    account = (
        Accounts.objects
        .select_for_update()
        .filter(id=account_id, user=user)
        .first()
    )
    if account is None:
        raise NotFound("账户不存在或无权限。")
    if account.status != Accounts.Status.ACTIVE:
        raise ValidationError({field_name: "账户未启用，不能转账。"})
    if is_system_investment_account(account=account):
        raise ValidationError({field_name: "投资账户不支持转账。"})
    return account


def _validate_transfer_pair(*, from_account: Accounts, to_account: Accounts, amount: Decimal) -> None:
    if from_account.id == to_account.id:
        raise ValidationError({"to_account_id": "转出账户和转入账户不能相同。"})
    if from_account.currency != to_account.currency:
        raise ValidationError({"to_account_id": "仅支持同币种账户之间转账。"})
    if amount <= 0:
        raise ValidationError({"amount": "转账金额必须大于 0。"})
    if (from_account.balance or Decimal("0")) < amount:
        raise ValidationError({"amount": "转出账户余额不足。"})


def create_transfer(*, user, from_account_id: int, to_account_id: int, amount: Decimal, note: str = "") -> Transfer:
    transfer_at = timezone.now()
    with db_transaction.atomic():
        from_account = _lock_account_for_transfer(user=user, account_id=from_account_id, field_name="from_account_id")
        to_account = _lock_account_for_transfer(user=user, account_id=to_account_id, field_name="to_account_id")
        _validate_transfer_pair(from_account=from_account, to_account=to_account, amount=amount)

        transfer = Transfer.objects.create(
            user=user,
            from_account=from_account,
            to_account=to_account,
            currency=from_account.currency,
            amount=amount,
            note=str(note or "").strip(),
        )

        out_tx = Transaction.objects.create(
            user=user,
            account=from_account,
            counterparty=to_account.name,
            category_name=TRANSFER_CATEGORY,
            remark=TRANSFER_OUT_REMARK,
            amount=Decimal("0") - amount,
            add_date=transfer_at,
            source=Transaction.Source.TRANSFER,
        )
        in_tx = Transaction.objects.create(
            user=user,
            account=to_account,
            counterparty=from_account.name,
            category_name=TRANSFER_CATEGORY,
            remark=TRANSFER_IN_REMARK,
            amount=amount,
            add_date=transfer_at,
            source=Transaction.Source.TRANSFER,
        )

        transfer.out_transaction = out_tx
        transfer.in_transaction = in_tx
        transfer.save(update_fields=["out_transaction", "in_transaction"])

        return (
            Transfer.objects
            .select_related("from_account", "to_account", "out_transaction", "in_transaction")
            .get(pk=transfer.id)
        )


def get_transfer_for_user(*, user, transfer_id: int) -> Transfer:
    transfer = (
        Transfer.objects
        .select_related(
            "from_account",
            "to_account",
            "out_transaction",
            "in_transaction",
            "reversed_out_transaction",
            "reversed_in_transaction",
        )
        .filter(id=transfer_id, user=user)
        .first()
    )
    if transfer is None:
        raise NotFound("转账不存在或无权限。")
    return transfer


def get_transfer_by_transaction(*, user, transaction_id: int) -> Transfer | None:
    return (
        Transfer.objects
        .select_related(
            "from_account",
            "to_account",
            "out_transaction",
            "in_transaction",
            "reversed_out_transaction",
            "reversed_in_transaction",
        )
        .filter(
            user=user,
        )
        .filter(
            Q(out_transaction_id=transaction_id)
            | Q(in_transaction_id=transaction_id)
        )
        .first()
    )


def reverse_transfer(*, user, transfer_id: int) -> Transfer:
    with db_transaction.atomic():
        transfer = (
            Transfer.objects
            .select_for_update()
            .filter(id=transfer_id, user=user)
            .first()
        )
        if transfer is None:
            raise NotFound("转账不存在或无权限。")
        if transfer.status == Transfer.Status.REVERSED:
            raise ValidationError("该转账已撤销，不能重复撤销。")
        if transfer.out_transaction_id is None or transfer.in_transaction_id is None:
            raise ValidationError("转账流水不完整，无法撤销。")

        Accounts.objects.select_for_update().filter(id__in=[transfer.from_account_id, transfer.to_account_id]).count()
        out_tx = Transaction.objects.select_for_update().get(pk=transfer.out_transaction_id)
        in_tx = Transaction.objects.select_for_update().get(pk=transfer.in_transaction_id)

        if out_tx.reversed_at is not None or in_tx.reversed_at is not None:
            raise ValidationError("该转账已撤销，不能重复撤销。")

        reverse_at = timezone.now()
        reversed_out_tx = Transaction.objects.create(
            user=user,
            account=transfer.from_account,
            counterparty=f"撤销: {transfer.to_account.name}",
            category_name="撤销",
            remark="转出冲正",
            amount=transfer.amount,
            add_date=reverse_at,
            reversal_of=out_tx,
            source=Transaction.Source.REVERSAL,
        )
        reversed_in_tx = Transaction.objects.create(
            user=user,
            account=transfer.to_account,
            counterparty=f"撤销: {transfer.from_account.name}",
            category_name="撤销",
            remark="转入冲正",
            amount=Decimal("0") - transfer.amount,
            add_date=reverse_at,
            reversal_of=in_tx,
            source=Transaction.Source.REVERSAL,
        )

        out_tx.reversed_at = reverse_at
        out_tx.save(update_fields=["reversed_at"])
        in_tx.reversed_at = reverse_at
        in_tx.save(update_fields=["reversed_at"])

        transfer.status = Transfer.Status.REVERSED
        transfer.reversed_at = reverse_at
        transfer.reversed_out_transaction = reversed_out_tx
        transfer.reversed_in_transaction = reversed_in_tx
        transfer.save(
            update_fields=[
                "status",
                "reversed_at",
                "reversed_out_transaction",
                "reversed_in_transaction",
            ]
        )

        return transfer
