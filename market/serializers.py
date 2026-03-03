from django.db.models import Case, IntegerField, Q, Value, When
from rest_framework import serializers
from shared.utils import normalize_code

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

    def validate(self, attrs):
        query = (attrs.get("q") or attrs.get("keyword") or "").strip()
        attrs["query"] = query
        attrs["query_upper"] = query.upper()

        raw_limit = attrs.get("limit")
        try:
            parsed = int(raw_limit) if raw_limit not in (None, "") else 20
        except (TypeError, ValueError):
            parsed = 20
        attrs["limit"] = max(1, min(parsed, 50))
        return attrs

    def build_queryset(self):
        query = self.validated_data.get("query", "")
        if not query:
            return Instrument.objects.none()

        query_upper = self.validated_data["query_upper"]
        limit = self.validated_data["limit"]

        return (
            Instrument.objects
            .filter(is_active=True)
            .filter(
                Q(short_code__icontains=query_upper)
                | Q(symbol__icontains=query_upper)
                | Q(name__icontains=query)
            )
            .annotate(
                priority=Case(
                    When(short_code__iexact=query_upper, then=Value(0)),
                    When(short_code__istartswith=query_upper, then=Value(1)),
                    When(name__istartswith=query, then=Value(2)),
                    default=Value(3),
                    output_field=IntegerField(),
                )
            )
            .order_by("priority", "short_code", "name")[:limit]
        )


class MarketLatestQuoteItemInputSerializer(serializers.Serializer):
    market = serializers.CharField()
    short_code = serializers.CharField()

    def validate_market(self, value):
        market = normalize_code(value)
        if not market:
            raise serializers.ValidationError("market 不能为空")
        return market

    def validate_short_code(self, value):
        short_code = normalize_code(value)
        if not short_code:
            raise serializers.ValidationError("short_code 不能为空")
        return short_code


class MarketLatestQuoteBatchSerializer(serializers.Serializer):
    items = MarketLatestQuoteItemInputSerializer(many=True, allow_empty=False)

    def validate_items(self, value):
        if len(value) > 300:
            raise serializers.ValidationError("items 最多 300 条")
        return value


class MarketWatchlistAddSerializer(serializers.Serializer):
    symbol = serializers.CharField()

    def validate_symbol(self, value):
        symbol = normalize_code(value)
        if not symbol:
            raise serializers.ValidationError("symbol 不能为空")
        return symbol


class MarketWatchlistDeleteSerializer(serializers.Serializer):
    symbol = serializers.CharField(required=False, allow_blank=True)
    market = serializers.CharField(required=False, allow_blank=True)
    short_code = serializers.CharField(required=False, allow_blank=True)

    def validate(self, attrs):
        symbol = normalize_code(attrs.get("symbol"))
        market = normalize_code(attrs.get("market"))
        short_code = normalize_code(attrs.get("short_code"))

        if not symbol and not (market and short_code):
            raise serializers.ValidationError("请提供 symbol，或同时提供 market + short_code")

        attrs["symbol"] = symbol
        attrs["market"] = market
        attrs["short_code"] = short_code
        return attrs
