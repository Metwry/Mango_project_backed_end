from decimal import Decimal

from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied

from .models import Position
from .services import (
    POSITION_ZERO,
    delete_zero_position,
    execute_buy,
    execute_sell,
    trim_decimal_str,
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

    def _get_request_user(self):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise PermissionDenied("未登录")
        return user


class InvestmentBuySerializer(InvestmentTradeBaseSerializer):
    def create(self, validated_data):
        user = self._get_request_user()
        return execute_buy(
            user=user,
            instrument_id=validated_data["instrument_id"],
            quantity=validated_data["quantity"],
            price=validated_data["price"],
            cash_account_id=validated_data["cash_account_id"],
            trade_at=validated_data.get("trade_at"),
        )


class InvestmentSellSerializer(InvestmentTradeBaseSerializer):
    def create(self, validated_data):
        user = self._get_request_user()
        return execute_sell(
            user=user,
            instrument_id=validated_data["instrument_id"],
            quantity=validated_data["quantity"],
            price=validated_data["price"],
            cash_account_id=validated_data["cash_account_id"],
            trade_at=validated_data.get("trade_at"),
        )


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

    @staticmethod
    def get_current_cost_price(obj: Position) -> str:
        return trim_decimal_str(obj.avg_cost or POSITION_ZERO)

    @staticmethod
    def get_current_quantity(obj: Position) -> str:
        return trim_decimal_str(obj.quantity or POSITION_ZERO)

    @staticmethod
    def get_current_value(obj: Position) -> str:
        return trim_decimal_str(obj.cost_total or POSITION_ZERO)


class PositionDeleteSerializer(serializers.Serializer):
    def save(self, **kwargs):
        request = self.context.get("request")
        user = getattr(request, "user", None)
        if user is None or not user.is_authenticated:
            raise PermissionDenied("未登录")

        instrument_id = self.context.get("instrument_id")
        if instrument_id is None:
            raise serializers.ValidationError("instrument_id 不能为空")

        return delete_zero_position(
            user=user,
            instrument_id=instrument_id,
        )
