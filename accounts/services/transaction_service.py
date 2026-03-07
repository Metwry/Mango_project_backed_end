from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from accounts.models import Transaction
from investment.models import InvestmentRecord
from shared.utils import quantize_decimal

from .currency_service import convert_amount_or_raise

ACCOUNT_PRECISION = Decimal("0.01")


def _is_linked_investment_cashflow(tx: Transaction) -> bool:
    if tx.source == Transaction.Source.INVESTMENT:
        return True

    if InvestmentRecord.objects.filter(cash_transaction_id=tx.id).exists():
        return True

    side = InvestmentRecord.Side.SELL if (tx.amount or Decimal("0")) > 0 else InvestmentRecord.Side.BUY
    candidates = InvestmentRecord.objects.filter(
        user_id=tx.user_id,
        cash_account_id=tx.account_id,
        trade_at=tx.add_date,
        side=side,
    ).only("quantity", "price")
    for row in candidates:
        gross = quantize_decimal((row.quantity or Decimal("0")) * (row.price or Decimal("0")), ACCOUNT_PRECISION)
        expected_amount = gross if side == InvestmentRecord.Side.SELL else Decimal("0") - gross
        if expected_amount == (tx.amount or Decimal("0")):
            return True
    return False


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
        if _is_linked_investment_cashflow(tx):
            raise ValidationError("投资交易产生的资金流水不允许撤销，请使用买卖交易进行冲销。")
        try:
            reversed_amount = Decimal("0") - convert_amount_or_raise(
                amount=tx.amount or Decimal("0"),
                from_currency=tx.currency,
                to_currency=tx.account.currency,
            )
        except ValueError as exc:
            raise ValidationError(str(exc))

        reverse_tx = Transaction.objects.create(
            user=user,
            account=tx.account,
            counterparty=f"撤销: {tx.counterparty}",
            category_name="撤销",
            amount=reversed_amount,
            add_date=timezone.now(),
            reversal_of=tx,
            source=Transaction.Source.REVERSAL,
        )

        tx.reversed_at = timezone.now()
        tx.save(update_fields=["reversed_at"])
        return reverse_tx


def create_transaction_for_user(*, serializer, user):
    return serializer.save(user=user)
