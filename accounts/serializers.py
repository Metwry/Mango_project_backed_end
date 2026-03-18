from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator

from .models import Accounts, Transaction, is_system_investment_account

# ed 账户序列化器
class AccountSerializer(serializers.ModelSerializer):
    user = serializers.HiddenField(default=serializers.CurrentUserDefault())

    class Meta:
        model = Accounts
        fields = "__all__"
        read_only_fields = ["id", "created_at", "updated_at"]
        validators = [
            UniqueTogetherValidator(
                queryset=Accounts.objects.all(),
                fields=["user", "name", "type", "currency"],
                message="您已存在同类型同币种的同名账户",
            )
        ]

    # 校验账户创建与更新请求，限制系统投资账户的手工维护范围。
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

# ed 交易记录序列化器
class TransactionSerializer(serializers.ModelSerializer):
    # 序列化返回给前端
    account_name = serializers.CharField(source="account.name", read_only=True)
    transfer_account_name = serializers.CharField(source="transfer_account.name", read_only=True)

    class Meta:
        model = Transaction
        fields = "__all__"

        read_only_fields = [
            "id",
            "created_at",
            "account_name",
            "transfer_account_name",
            "currency",
            "balance_after",
            "user",
            "reversal_of",
            "reversed_at",
            "source",
        ]
        extra_kwargs = {
            "counterparty": {"required": False, "allow_blank": True},
            "category_name": {"required": False, "allow_blank": True},
            "remark": {"required": False, "allow_blank": True},
            "transfer_account": {"required": False, "allow_null": True},
        }

    # ed 校验交易所选账户是否归属于当前用户且允许手工记账或转出。
    def validate_account(self, value):
        req_user = self.context["request"].user
        if value.user_id != req_user.id:
            raise serializers.ValidationError("您无权使用该账户。")
        # 交易创建统一走服务层，需在请求层提前挡住系统投资账户。
        if is_system_investment_account(account=value):
            raise serializers.ValidationError("投资账户不允许手工记账或转账。")
        return value

    # ed 校验转账目标账户是否归属于当前用户。
    def validate_transfer_account(self, value):
        if value is None:
            return value
        req_user = self.context["request"].user
        if value.user_id != req_user.id:
            raise serializers.ValidationError("您无权使用该账户作为转入账户。")
        return value

    # 校验交易创建与更新规则。
    def validate(self, attrs):
        attrs = super().validate(attrs)
        account = attrs.get("account")
        transfer_account = attrs.get("transfer_account")

        if account is None:
            raise serializers.ValidationError({"account": "account 为必填项"})

        if transfer_account is not None:
            return attrs
        else:
            if not attrs.get("counterparty"):
                raise serializers.ValidationError({"counterparty": "手工记账必须填写 counterparty"})
            if attrs.get("amount") is None:
                raise serializers.ValidationError({"amount": "amount 为必填项"})

        return attrs

# 删除交易记录序列化器
class TransactionDeleteQuerySerializer(serializers.Serializer):
    id = serializers.CharField(required=False, allow_blank=True)
    source = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        tx_id_raw = str(attrs.get("id") or "").strip()
        source = str(attrs.get("source") or "").strip()

        if bool(tx_id_raw) == bool(source):
            raise serializers.ValidationError({"message": "请且仅请提供 id 或 source 其中一个参数。"})

        if tx_id_raw:
            try:
                attrs["id"] = int(tx_id_raw)
            except (TypeError, ValueError) as exc:
                raise serializers.ValidationError({"message": "交易ID格式不正确。"}) from exc
            attrs.pop("source", None)
            return attrs

        valid_sources = {
            Transaction.Source.MANUAL,
            Transaction.Source.INVESTMENT,
            Transaction.Source.TRANSFER,
            Transaction.Source.REVERSAL,
        }
        if source not in valid_sources:
            raise serializers.ValidationError({"message": "source 参数无效。"})

        attrs["source"] = source
        attrs.pop("id", None)
        return attrs
