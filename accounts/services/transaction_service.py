from decimal import Decimal

from django.db import transaction as db_transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, ValidationError

from accounts.models import Accounts, Transaction, is_system_investment_account
from investment.models import InvestmentRecord
from common.utils.decimal_utils import quantize_decimal

from .currency_service import convert_amount_or_raise

ACCOUNT_PRECISION = Decimal("0.01")
TRANSFER_CATEGORY = "转账"


def _lock_transaction_or_raise(*, user, tx_id: int) -> Transaction:
    tx = (
        Transaction.objects
        .select_for_update()
        .filter(pk=tx_id, user=user)
        .first()
    )
    if tx is None:
        raise NotFound("交易不存在或无权限。")
    return tx


def _lock_account_for_transaction(*, user, account_id: int) -> Accounts:
    account = (
        Accounts.objects
        .select_for_update()
        .filter(id=account_id, user=user)
        .first()
    )
    if account is None:
        raise NotFound("账户不存在或无权限。")
    return account


def _create_transaction_row(
    *,
    user,
    account: Accounts,
    counterparty: str,
    amount: Decimal,
    category_name: str,
    add_date,
    source: str,
    remark: str = "",
    transfer_account=None,
    reversal_of=None,
) -> Transaction:
    if account.user_id != user.id:
        raise ValidationError("账户与当前用户不匹配。")

    account.balance = (account.balance or Decimal("0")) + (amount or Decimal("0"))
    account.save(update_fields=["balance", "updated_at"])

    return Transaction.objects.create(
        user=user,
        account=account,
        transfer_account=transfer_account,
        counterparty=counterparty,
        amount=amount,
        balance_after=account.balance,
        category_name=category_name,
        remark=remark,
        currency=account.currency,
        add_date=add_date,
        source=source,
        reversal_of=reversal_of,
    )


# 判断一条资金流水是否与投资买卖记录相关联。
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


# 锁定并校验转账参与账户。
def _lock_transfer_accounts(*, user, from_account_id: int, to_account_id: int) -> tuple[Accounts, Accounts]:
    if from_account_id == to_account_id:
        raise ValidationError({"transfer_account": "转出账户和转入账户不能相同。"})

    account_map = {
        row.id: row
        for row in (
            Accounts.objects
            .select_for_update()
            .filter(user=user, id__in=[from_account_id, to_account_id])
            .order_by("id")
        )
    }

    from_account = account_map.get(from_account_id)
    if from_account is None:
        raise NotFound("转出账户不存在或无权限。")

    to_account = account_map.get(to_account_id)
    if to_account is None:
        raise NotFound("转入账户不存在或无权限。")

    for field_name, account in (("account", from_account), ("transfer_account", to_account)):
        if account.status != Accounts.Status.ACTIVE:
            raise ValidationError({field_name: "账户未启用，不能转账。"})
        if is_system_investment_account(account=account):
            raise ValidationError({field_name: "投资账户不支持转账。"})

    if from_account.currency != to_account.currency:
        raise ValidationError({"transfer_account": "仅支持同币种账户之间转账。"})

    return from_account, to_account


def create_transaction_for_locked_account(
    *,
    user,
    account: Accounts,
    counterparty: str,
    amount: Decimal,
    category_name: str,
    add_date,
    source: str,
    remark: str = "",
    transfer_account=None,
    reversal_of=None,
) -> Transaction:
    return _create_transaction_row(
        user=user,
        account=account,
        counterparty=counterparty,
        amount=amount,
        category_name=category_name,
        add_date=add_date,
        source=source,
        remark=remark,
        transfer_account=transfer_account,
        reversal_of=reversal_of,
    )


# 创建单条转账记录，并同步更新双方账户余额。
def _create_transfer_transaction(*, serializer, user) -> Transaction:
    validated = dict(serializer.validated_data)
    amount = validated.get("amount")
    if amount is None or amount <= 0:
        raise ValidationError({"amount": "转账金额必须大于 0。"})

    raw_from_account = validated["account"]
    raw_to_account = validated["transfer_account"]
    add_date = validated.get("add_date") or timezone.now()
    remark = str(validated.get("remark") or "").strip()

    with db_transaction.atomic():
        from_account, to_account = _lock_transfer_accounts(
            user=user,
            from_account_id=raw_from_account.id,
            to_account_id=raw_to_account.id,
        )
        if (from_account.balance or Decimal("0")) < amount:
            raise ValidationError({"amount": "转出账户余额不足。"})

        from_account.balance = (from_account.balance or Decimal("0")) - amount
        to_account.balance = (to_account.balance or Decimal("0")) + amount
        from_account.save(update_fields=["balance", "updated_at"])
        to_account.save(update_fields=["balance", "updated_at"])

        return Transaction.objects.create(
            user=user,
            account=from_account,
            transfer_account=to_account,
            counterparty=to_account.name,
            category_name=validated.get("category_name") or TRANSFER_CATEGORY,
            remark=remark,
            amount=amount,
            add_date=add_date,
            source=Transaction.Source.TRANSFER,
            currency=from_account.currency,
            balance_after=from_account.balance,
        )


# 收集指定原交易对应的冲正流水。
def _collect_linked_reversal_rows(*, user, original_ids: list[int]) -> list[Transaction]:
    if not original_ids:
        return []
    return list(
        Transaction.objects
        .select_for_update()
        .filter(user=user, reversal_of_id__in=original_ids)
    )


# 实际删除交易行，并解除投资记录上的资金流水绑定。
def _delete_rows(*, user, rows: list[Transaction]) -> int:
    if not rows:
        return 0
    ids = sorted({row.id for row in rows})
    InvestmentRecord.objects.filter(user=user, cash_transaction_id__in=ids).update(cash_transaction=None)
    reversal_rows = [row for row in rows if row.reversal_of_id is not None]
    original_rows = [row for row in rows if row.reversal_of_id is None]
    for row in [*reversal_rows, *original_rows]:
        row.delete()
    return len(ids)


# 删除单条交易；若删除的是原交易，会连带删除对应冲正流水。
def delete_single_transaction(*, user, tx_id: int) -> None:
    with db_transaction.atomic():
        tx = _lock_transaction_or_raise(user=user, tx_id=tx_id)
        rows = [tx]
        if tx.reversal_of_id is None:
            rows.extend(_collect_linked_reversal_rows(user=user, original_ids=[tx.id]))
        _delete_rows(user=user, rows=rows)


# 按 source 批量删除交易；删除原交易时会一并删除对应冲正流水。
def delete_transactions_by_source(*, user, source: str) -> dict:
    with db_transaction.atomic():
        base_rows = list(
            Transaction.objects
            .select_for_update()
            .filter(user=user, source=source)
            .order_by("-add_date", "-id")
        )
        if source == Transaction.Source.REVERSAL:
            deleted_rows = _delete_rows(user=user, rows=base_rows)
            return {
                "source": source,
                "deleted_count": deleted_rows,
            }

        reversal_rows = _collect_linked_reversal_rows(
            user=user,
            original_ids=[row.id for row in base_rows if row.reversal_of_id is None],
        )
        deleted_rows = _delete_rows(user=user, rows=[*base_rows, *reversal_rows])
        return {
            "source": source,
            "deleted_count": deleted_rows,
        }


# 撤销指定交易，仅支持手工记账原交易。
def reverse_transaction(*, user, tx_id: int) -> Transaction:
    with db_transaction.atomic():
        try:
            tx = (
                Transaction.objects
                .select_for_update()
                .select_related("account")
                .get(pk=tx_id, user=user)
            )
        except Transaction.DoesNotExist as exc:
            raise NotFound("交易不存在或无权限。") from exc

        if tx.reversal_of_id is not None:
            raise ValidationError("撤销交易不能再次撤销。")
        if tx.reversed_at is not None:
            raise ValidationError("该交易已撤销，不能重复撤销。")
        if tx.source == Transaction.Source.TRANSFER:
            raise ValidationError("转账记录不支持撤销，请直接删除记录。")
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

        account = _lock_account_for_transaction(user=user, account_id=tx.account_id)
        reverse_tx = _create_transaction_row(
            user=user,
            account=account,
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


# 使用序列化器为当前用户创建交易记录或转账记录。
def create_transaction_for_user(*, serializer, user):
    if serializer.validated_data.get("transfer_account") is not None:
        return _create_transfer_transaction(serializer=serializer, user=user)

    validated = dict(serializer.validated_data)
    with db_transaction.atomic():
        account = _lock_account_for_transaction(user=user, account_id=validated["account"].id)
        return _create_transaction_row(
            user=user,
            account=account,
            counterparty=validated["counterparty"],
            amount=validated["amount"],
            category_name=validated["category_name"],
            add_date=validated.get("add_date") or timezone.now(),
            source=Transaction.Source.MANUAL,
            remark=str(validated.get("remark") or "").strip(),
        )

