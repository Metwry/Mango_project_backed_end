from django.db import transaction as db_transaction
from rest_framework.exceptions import ValidationError

from accounts.models import Accounts
from investment.models import Position
from investment.services import sync_investment_account_for_user
from shared.utils import normalize_code

from .currency_service import convert_amount_or_raise

TRUE_VALUES = {"1", "true", "yes", "on"}


def should_include_archived(raw_value) -> bool:
    return str(raw_value or "").strip().lower() in TRUE_VALUES


def get_user_accounts_queryset(*, user, include_archived: bool):
    queryset = Accounts.objects.filter(user=user).order_by("-balance")
    if not include_archived:
        queryset = queryset.exclude(status=Accounts.Status.ARCHIVED)
    return queryset


def create_account_for_user(*, serializer, user):
    return serializer.save(user=user)


def update_account_from_serializer(*, serializer):
    instance: Accounts = serializer.instance
    previous_currency = instance.currency
    next_currency = normalize_code(serializer.validated_data.get("currency", previous_currency)) or previous_currency

    extra_save_kwargs = {}
    if next_currency != previous_currency:
        try:
            converted_balance = convert_amount_or_raise(
                amount=instance.balance,
                from_currency=previous_currency,
                to_currency=next_currency,
            )
        except ValueError as exc:
            raise ValidationError({"currency": str(exc)})
        extra_save_kwargs = {"currency": next_currency, "balance": converted_balance}

    with db_transaction.atomic():
        updated = serializer.save(**extra_save_kwargs)
        if updated.type == Accounts.AccountType.INVESTMENT and updated.currency != previous_currency:
            synced = sync_investment_account_for_user(
                user=updated.user,
                target_currency=updated.currency,
            )
            if synced is not None:
                updated = synced
    return updated


def archive_account(*, account: Accounts, user) -> dict | None:
    if account.type == Accounts.AccountType.INVESTMENT:
        has_positions = Position.objects.filter(user=user, quantity__gt=0).exists()
        if has_positions:
            return {
                "code": "investment_account_delete_blocked",
                "message": "投资账户存在持仓，无法删除，请先卖出全部持仓。",
            }

    if account.status != Accounts.Status.ARCHIVED:
        account.status = Accounts.Status.ARCHIVED
        account.save(update_fields=["status", "updated_at"])

    return None
