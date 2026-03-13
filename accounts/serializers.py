from decimal import Decimal

from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from .models import Accounts, Transaction, Transfer, is_system_investment_account


class AccountSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Accounts
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]

        validators = [
            UniqueTogetherValidator(
                queryset=Accounts.objects.all(),
                fields=["user", "name", "type","currency"],
                message="您已存在同类型同币种的同名账户",
            )
        ]

    def validate(self, attrs):
        attrs = super().validate(attrs)
        instance = getattr(self, "instance", None)

        if instance is None:
            account_type = attrs.get("type")
            account_name = str(attrs.get("name") or "").strip()
            if is_system_investment_account(account_type=account_type, account_name=account_name):
                raise serializers.ValidationError({"message": "投资账户由系统自动维护，不能手动创建。"})

            return attrs

        if not is_system_investment_account(account=instance):
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
            "remark",
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
        if is_system_investment_account(account=value):
            raise serializers.ValidationError("投资账户不允许手工记账，通过持仓买卖自动计算。")
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


class TransferCreateSerializer(serializers.Serializer):
    from_account_id = serializers.IntegerField(min_value=1)
    to_account_id = serializers.IntegerField(min_value=1)
    amount = serializers.DecimalField(max_digits=12, decimal_places=2, min_value=Decimal("0.01"))
    note = serializers.CharField(required=False, allow_blank=True, max_length=64)


class TransferAccountSummarySerializer(serializers.Serializer):
    id = serializers.IntegerField()
    name = serializers.CharField()
    currency = serializers.CharField()
    balance_after = serializers.CharField()


class TransferSerializer(serializers.ModelSerializer):
    from_account = serializers.SerializerMethodField()
    to_account = serializers.SerializerMethodField()
    out_transaction_id = serializers.IntegerField(read_only=True)
    in_transaction_id = serializers.IntegerField(read_only=True)
    reversed_out_transaction_id = serializers.IntegerField(read_only=True)
    reversed_in_transaction_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = Transfer
        fields = [
            "id",
            "currency",
            "amount",
            "status",
            "note",
            "from_account",
            "to_account",
            "out_transaction_id",
            "in_transaction_id",
            "reversed_out_transaction_id",
            "reversed_in_transaction_id",
            "created_at",
            "reversed_at",
        ]
        read_only_fields = fields

    @staticmethod
    def _account_payload(*, account: Accounts, balance_after) -> dict:
        return {
            "id": account.id,
            "name": account.name,
            "currency": account.currency,
            "balance_after": str(balance_after),
        }

    def get_from_account(self, obj: Transfer) -> dict:
        balance_after = obj.out_transaction.balance_after if obj.out_transaction_id else obj.from_account.balance
        return self._account_payload(account=obj.from_account, balance_after=balance_after)

    def get_to_account(self, obj: Transfer) -> dict:
        balance_after = obj.in_transaction.balance_after if obj.in_transaction_id else obj.to_account.balance
        return self._account_payload(account=obj.to_account, balance_after=balance_after)
