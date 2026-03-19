from rest_framework import serializers
from common.utils.code_utils import normalize_code

from .models import Instrument


class InstrumentSearchItemSerializer(serializers.ModelSerializer):
    instrument_id = serializers.IntegerField(source="id")

    class Meta:
        model = Instrument
        fields = ["instrument_id", "symbol", "short_code", "name", "market"]


class MarketInstrumentSearchQuerySerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True)
    keyword = serializers.CharField(required=False, allow_blank=True)
    limit = serializers.CharField(required=False, allow_blank=True)

    # 规范化搜索关键词并解析安全的返回数量上限。
    def validate(self, attrs):
        query = (attrs.get("q") or attrs.get("keyword") or "").strip()
        attrs["query"] = query

        raw_limit = attrs.get("limit")
        try:
            parsed = int(raw_limit) if raw_limit not in (None, "") else 20
        except (TypeError, ValueError):
            parsed = 20
        attrs["limit"] = max(1, min(parsed, 50))
        return attrs


class MarketLatestQuoteItemInputSerializer(serializers.Serializer):
    market = serializers.CharField()
    short_code = serializers.CharField()

    # 校验并标准化市场代码。
    def validate_market(self, value):
        market = normalize_code(value)
        if not market:
            raise serializers.ValidationError("market 不能为空")
        return market

    # 校验并标准化标的短代码。
    def validate_short_code(self, value):
        short_code = normalize_code(value)
        if not short_code:
            raise serializers.ValidationError("short_code 不能为空")
        return short_code


class MarketLatestQuoteBatchSerializer(serializers.Serializer):
    items = MarketLatestQuoteItemInputSerializer(many=True, allow_empty=False)

    # 限制批量查询的标的数量，避免单次请求过大。
    def validate_items(self, value):
        if len(value) > 300:
            raise serializers.ValidationError("items 最多 300 条")
        return value

