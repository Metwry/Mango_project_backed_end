from rest_framework import serializers

from common.normalize import normalize_code

from .models import Instrument


class NormalizedCodeField(serializers.CharField):
    def __init__(self, *, empty_message: str | None = None, fallback: str | None = None, **kwargs):
        self.empty_message = empty_message
        self.fallback = fallback
        if empty_message and "allow_blank" not in kwargs:
            kwargs["allow_blank"] = True
        super().__init__(**kwargs)

    def to_internal_value(self, data):
        value = normalize_code(super().to_internal_value(data))
        if value:
            return value
        if self.fallback is not None:
            return self.fallback
        if self.empty_message:
            raise serializers.ValidationError(self.empty_message)
        return value


# API 请求序列化器。
class InstrumentSearchQueryRequestSerializer(serializers.Serializer):
    q = serializers.CharField(required=False, allow_blank=True, trim_whitespace=True)
    limit = serializers.IntegerField(required=False, min_value=1, max_value=50, default=20)

    # 规范化搜索关键词。
    def validate(self, attrs):
        attrs["query"] = (attrs.get("q") or "").strip()
        return attrs


class LatestQuoteItemRequestSerializer(serializers.Serializer):
    market = NormalizedCodeField(empty_message="market 不能为空")
    short_code = NormalizedCodeField(empty_message="short_code 不能为空")


class LatestQuoteBatchRequestSerializer(serializers.Serializer):
    items = LatestQuoteItemRequestSerializer(many=True, allow_empty=False)

    # 限制批量查询的标的数量，避免单次请求过大。
    def validate_items(self, value):
        if len(value) > 300:
            raise serializers.ValidationError("items 最多 300 条")
        return value


class FxRatesQueryRequestSerializer(serializers.Serializer):
    base = NormalizedCodeField(required=False, allow_blank=True, default="USD", fallback="USD")


class WatchlistAddRequestSerializer(serializers.Serializer):
    symbol = NormalizedCodeField(empty_message="symbol 不能为空")


class WatchlistDeleteRequestSerializer(serializers.Serializer):
    market = NormalizedCodeField(empty_message="market 不能为空")
    short_code = NormalizedCodeField(empty_message="short_code 不能为空")


# API 响应序列化器。
class InstrumentSearchItemSerializer(serializers.ModelSerializer):
    instrument_id = serializers.IntegerField(source="id")

    class Meta:
        model = Instrument
        fields = ["instrument_id", "symbol", "short_code", "name", "market"]


class InstrumentSearchResponseSerializer(serializers.Serializer):
    results = InstrumentSearchItemSerializer(many=True)


class MarketSnapshotQuoteSerializer(serializers.Serializer):
    short_code = serializers.CharField()
    name = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    prev_close = serializers.FloatField(required=False, allow_null=True)
    day_high = serializers.FloatField(required=False, allow_null=True)
    day_low = serializers.FloatField(required=False, allow_null=True)
    price = serializers.FloatField(required=False, allow_null=True)
    pct = serializers.FloatField(required=False, allow_null=True)
    volume = serializers.FloatField(required=False, allow_null=True)
    logo_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    logo_color = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class MarketSnapshotMarketSerializer(serializers.Serializer):
    market = serializers.CharField()
    quotes = MarketSnapshotQuoteSerializer(many=True)


class MarketSnapshotResponseSerializer(serializers.Serializer):
    updated_at = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    markets = MarketSnapshotMarketSerializer(many=True)


class LatestQuoteItemResponseSerializer(serializers.Serializer):
    market = serializers.CharField()
    short_code = serializers.CharField()
    latest_price = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    logo_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    logo_color = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class LatestQuoteBatchResponseSerializer(serializers.Serializer):
    quotes = LatestQuoteItemResponseSerializer(many=True)


class WatchlistInstrumentResponseSerializer(serializers.Serializer):
    symbol = serializers.CharField()
    short_code = serializers.CharField()
    name = serializers.CharField()
    market = serializers.CharField()
    logo_url = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    logo_color = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class WatchlistAddResponseSerializer(serializers.Serializer):
    created = serializers.BooleanField()
    watchlist_item_id = serializers.IntegerField()
    instrument = WatchlistInstrumentResponseSerializer()
    quote_ready = serializers.BooleanField()
    quote_source = serializers.CharField()


class WatchlistDeleteResponseSerializer(serializers.Serializer):
    deleted = serializers.IntegerField()
    updated_markets = serializers.ListField(child=serializers.CharField())


class FxRatesResponseSerializer(serializers.Serializer):
    base = serializers.CharField()
    updated_at = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    rates = serializers.DictField(child=serializers.FloatField())


class IndexSnapshotItemSerializer(serializers.Serializer):
    instrument_id = serializers.IntegerField(required=False, allow_null=True)
    name = serializers.CharField()
    prev_close = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    day_high = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    day_low = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    pct = serializers.CharField(required=False, allow_blank=True, allow_null=True)


class IndexSnapshotResponseSerializer(serializers.Serializer):
    updated_at = serializers.CharField(required=False, allow_blank=True, allow_null=True)
    items = IndexSnapshotItemSerializer(many=True)

