from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from .models import Accounts, Transaction


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

class TransactionSerializer(serializers.ModelSerializer):
    account_name = serializers.CharField(source="account.name", read_only=True)

    currency = serializers.CharField(read_only=True)
    balance_after = serializers.DecimalField(max_digits=12, decimal_places=2, read_only=True)
    user = serializers.PrimaryKeyRelatedField(read_only=True)

    # 新增：冲正信息只读展示
    reversal_of = serializers.PrimaryKeyRelatedField(read_only=True)
    reversed_at = serializers.DateTimeField(read_only=True)
    source = serializers.CharField(read_only=True)

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
            "source",
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
            "source",
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


class TransactionDeleteRequestSerializer(serializers.Serializer):
    mode = serializers.ChoiceField(choices=["single", "activity"])
    transaction_id = serializers.IntegerField(required=False, min_value=1)
    activity_type = serializers.ChoiceField(
        required=False,
        choices=["manual", "investment", "reversed"],
    )

    def validate(self, attrs):
        mode = attrs.get("mode")
        if mode == "single":
            if attrs.get("transaction_id") is None:
                raise serializers.ValidationError({"transaction_id": "mode=single 时必填"})
            return attrs
        if attrs.get("activity_type") is None:
            raise serializers.ValidationError({"activity_type": "mode=activity 时必填"})
        return attrs
