from decimal import Decimal

from django.core.cache import cache
from django.db import transaction as db_transaction
from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from investment.services import sync_investment_account_for_user
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY
from shared.utils import normalize_code, quantize_decimal, to_decimal

from .models import Accounts, Transaction

ACCOUNT_PRECISION = Decimal("0.01")


def _load_cached_usd_rates() -> dict[str, Decimal]:
    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    raw_rates = payload.get("rates") if isinstance(payload, dict) else None
    rates: dict[str, Decimal] = {"USD": Decimal("1")}
    if not isinstance(raw_rates, dict):
        return rates

    for code, raw_value in raw_rates.items():
        ccy = normalize_code(code)
        value = to_decimal(raw_value)
        if not ccy or value is None or value <= 0:
            continue
        rates[ccy] = value

    rates["USD"] = Decimal("1")
    return rates


def _convert_balance_or_raise(*, amount: Decimal, from_currency: str, to_currency: str) -> Decimal:
    source = normalize_code(from_currency)
    target = normalize_code(to_currency)
    if not source or not target or source == target:
        return amount

    rates = _load_cached_usd_rates()
    source_rate = rates.get(source)
    target_rate = rates.get(target)
    if source_rate is None or target_rate is None or source_rate <= 0 or target_rate <= 0:
        raise serializers.ValidationError(
            {"currency": f"缺少汇率对数据：{source}/{target}，请先刷新汇率后重试。"}
        )

    converted = (amount / source_rate) * target_rate
    return quantize_decimal(converted, ACCOUNT_PRECISION)


class AccountSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Accounts
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

        validators = [
            UniqueTogetherValidator(
                queryset=Accounts.objects.all(),
                fields=["user", "name", "currency"],
                message="您已存在该币种下的同名账户",
            )
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, "instance", None)

        if instance is None:
            account_type = attrs.get("type")
            if account_type == Accounts.AccountType.INVESTMENT:
                raise serializers.ValidationError({"type": "投资账户由系统自动维护，不能手动创建。"})
            return attrs

        if instance.type != Accounts.AccountType.INVESTMENT:
            return attrs

        blocked_fields = []
        for field in ("name", "type", "balance", "status"):
            if field in attrs and attrs[field] != getattr(instance, field):
                blocked_fields.append(field)

        if blocked_fields:
            raise serializers.ValidationError(
                {field: "投资账户仅允许修改币种。" for field in blocked_fields}
            )

        return attrs

    def update(self, instance, validated_data):
        previous_currency = instance.currency
        next_currency = normalize_code(validated_data.get("currency", previous_currency)) or previous_currency

        if next_currency != previous_currency:
            converted_balance = _convert_balance_or_raise(
                amount=instance.balance,
                from_currency=previous_currency,
                to_currency=next_currency,
            )
            validated_data["balance"] = converted_balance

        with db_transaction.atomic():
            updated = super().update(instance, validated_data)

            if updated.type == Accounts.AccountType.INVESTMENT and updated.currency != previous_currency:
                synced = sync_investment_account_for_user(
                    user=updated.user,
                    target_currency=updated.currency,
                )
                if synced is not None:
                    updated = synced

        return updated


class TransactionSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)

    currency = serializers.CharField(read_only=True)
    balance_after = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    # 新增：冲正信息只读展示
    reversal_of = serializers.PrimaryKeyRelatedField(read_only=True)
    reversed_at = serializers.DateTimeField(read_only=True)

    class Meta:
        model = Transaction
        fields = [
            "id",
            "counterparty",
            "amount",
            "category_name",
            "currency",
            "account",
            "account_name",
            "balance_after",
            "user",
            "add_date",
            "created_at",
            "reversal_of",
            "reversed_at",
        ]
        read_only_fields = [
            "id",
            "created_at",
            "account_name",
            "currency",
            "balance_after",
            "user",
            "reversal_of",
            "reversed_at",
        ]

    def validate_account(self, value):
        req_user = self.context["request"].user
        if value.user_id != req_user.id:
            raise serializers.ValidationError("您无权使用该账户进行记账。")
        if value.type == Accounts.AccountType.INVESTMENT:
            raise serializers.ValidationError("投资账户不允许手工记账，请通过持仓买卖自动计算。")
        return value

    def validate(self, attrs):
        if self.instance:
            if "account" in attrs and attrs["account"].id != self.instance.account_id:
                raise serializers.ValidationError({"account": "交易创建后不能修改 account"})
            if "amount" in attrs and attrs["amount"] != self.instance.amount:
                raise serializers.ValidationError({"amount": "交易创建后不能修改 amount"})
            if "add_date" in attrs and attrs["add_date"] != self.instance.add_date:
                raise serializers.ValidationError({"add_date": "交易创建后不能修改 add_date"})
        return attrs
