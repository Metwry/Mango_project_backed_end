from django.db import transaction as db_transaction
from rest_framework.exceptions import ValidationError

from accounts.models import Accounts, is_system_investment_account
from investment.services.account_service import sync_investment_account_for_user
from shared.utils import normalize_code

from .currency_service import convert_amount_or_raise

TRUE_VALUES = {"1", "true", "yes", "on"}

# 判断归档字段的值
def should_include_archived(raw_value) -> bool:
    return str(raw_value or "").strip().lower() in TRUE_VALUES

# 返回账户信息
def get_user_accounts_queryset(*, user, include_archived: bool):
    queryset = Accounts.objects.filter(user=user).order_by("-balance")
    if not include_archived:
        queryset = queryset.exclude(status=Accounts.Status.ARCHIVED)
    return queryset

# 通过userid，参数，修改账户
def update_account_from_serializer(*, serializer):
    instance: Accounts = serializer.instance
    previous_currency = instance.currency
    next_currency = normalize_code(serializer.validated_data.get("currency", previous_currency))

    # 处理投资账户的数据更新
    if is_system_investment_account(account=instance):
        with db_transaction.atomic():
            if next_currency == previous_currency:
                return serializer.save()
            try:
                synced = sync_investment_account_for_user(
                    user=instance.user,
                    target_currency=next_currency,
                )
            except ValueError as exc:
                raise ValidationError({"currency": str(exc)})
            if synced is None:
                raise ValidationError({"currency": "系统投资账户同步失败。"})
            return synced

    # 处理常规账户的数据更新
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
        return serializer.save(**extra_save_kwargs)

# 归档投资账户
def archive_account(*, account: Accounts, user) -> dict | None:
    if is_system_investment_account(account=account):
        return {
            "code": "investment_account_delete_blocked",
            "message": "系统投资账户由系统维护，不能删除。",
        }

    if account.status != Accounts.Status.ARCHIVED:
        account.status = Accounts.Status.ARCHIVED
        account.save(update_fields=["status", "updated_at"])

    return None
