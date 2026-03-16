from decimal import Decimal

from rest_framework import serializers

from shared.utils import normalize_datetime_to_utc, quantize_decimal, trim_decimal_str

from .models import InvestmentRecord, Position
from .services import (
    POSITION_ZERO,
)


class InvestmentTradeBaseSerializer(serializers.Serializer):
    instrument_id = serializers.IntegerField(min_value=1)
    quantity = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0.000001"),
    )
    price = serializers.DecimalField(
        max_digits=20,
        decimal_places=6,
        min_value=Decimal("0.000001"),
    )
    cash_account_id = serializers.IntegerField(min_value=1)
    trade_at = serializers.DateTimeField(required=False)


class InvestmentBuySerializer(InvestmentTradeBaseSerializer):
    pass


class InvestmentSellSerializer(InvestmentTradeBaseSerializer):
    pass


class PositionListItemSerializer(serializers.ModelSerializer):
    instrument_id = serializers.IntegerField()
    short_code = serializers.CharField(source="instrument.short_code")
    name = serializers.CharField(source="instrument.name")
    market_type = serializers.CharField(source="instrument.market")
    current_cost_price = serializers.SerializerMethodField()
    current_quantity = serializers.SerializerMethodField()
    current_value = serializers.SerializerMethodField()

    class Meta:
        model = Position
        fields = [
            "instrument_id",
            "short_code",
            "name",
            "market_type",
            "current_cost_price",
            "current_quantity",
            "current_value",
        ]

    # 返回持仓当前成本价的字符串展示值。
    @staticmethod
    def get_current_cost_price(obj: Position) -> str:
        return trim_decimal_str(obj.avg_cost or POSITION_ZERO)

    # 返回持仓当前数量的字符串展示值。
    @staticmethod
    def get_current_quantity(obj: Position) -> str:
        return trim_decimal_str(obj.quantity or POSITION_ZERO)

    # 返回持仓当前成本总额的字符串展示值。
    @staticmethod
    def get_current_value(obj: Position) -> str:
        return trim_decimal_str(obj.cost_total or POSITION_ZERO)


class PositionDeleteSerializer(serializers.Serializer):
    instrument_id = serializers.IntegerField(min_value=1)


class InvestmentHistoryQuerySerializer(serializers.Serializer):
    account_id = serializers.IntegerField(required=False, min_value=1)
    instrument_id = serializers.IntegerField(required=False, min_value=1)
    side = serializers.ChoiceField(required=False, choices=InvestmentRecord.Side.choices)
    start = serializers.DateTimeField(required=False)
    end = serializers.DateTimeField(required=False)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=1000, default=100)
    offset = serializers.IntegerField(required=False, min_value=0, default=0)

    # 将时间参数统一规范化为 UTC 时区时间。
    @staticmethod
    def _normalize_datetime(value):
        return normalize_datetime_to_utc(value)

    # 校验历史查询时间范围并统一起止时间格式。
    def validate(self, attrs):
        start = attrs.get("start")
        end = attrs.get("end")
        if start is not None:
            attrs["start"] = self._normalize_datetime(start)
        if end is not None:
            attrs["end"] = self._normalize_datetime(end)
        if attrs.get("start") is not None and attrs.get("end") is not None and attrs["start"] > attrs["end"]:
            raise serializers.ValidationError("start 不能晚于 end")
        return attrs


class InvestmentHistoryItemSerializer(serializers.ModelSerializer):
    instrument_symbol = serializers.CharField(source="instrument.symbol", read_only=True)
    instrument_short_code = serializers.CharField(source="instrument.short_code", read_only=True)
    instrument_name = serializers.CharField(source="instrument.name", read_only=True)
    cash_account_name = serializers.CharField(source="cash_account.name", read_only=True)
    cash_account_currency = serializers.CharField(source="cash_account.currency", read_only=True)
    cash_flow_amount = serializers.SerializerMethodField()
    cash_transaction_id = serializers.IntegerField(read_only=True)

    class Meta:
        model = InvestmentRecord
        fields = [
            "id",
            "side",
            "trade_at",
            "instrument_id",
            "instrument_symbol",
            "instrument_short_code",
            "instrument_name",
            "quantity",
            "price",
            "realized_pnl",
            "cash_account_id",
            "cash_account_name",
            "cash_account_currency",
            "cash_flow_amount",
            "cash_transaction_id",
            "created_at",
        ]

    # 计算并返回该笔投资交易对应的资金流金额。
    @staticmethod
    def get_cash_flow_amount(obj: InvestmentRecord) -> str:
        if obj.cash_transaction_id:
            return trim_decimal_str(obj.cash_transaction.amount or Decimal("0"))
        gross = quantize_decimal((obj.quantity or Decimal("0")) * (obj.price or Decimal("0")), Decimal("0.01"))
        amount = gross if obj.side == InvestmentRecord.Side.SELL else Decimal("0") - gross
        return trim_decimal_str(amount)
