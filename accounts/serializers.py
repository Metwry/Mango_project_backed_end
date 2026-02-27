from rest_framework import serializers
from rest_framework.validators import UniqueTogetherValidator
from django.conf import settings
from django.core.cache import cache
from django.db.models import Q, Case, When, Value, IntegerField
from django.utils import timezone
from .models import Accounts, Transaction, WatchlistItem, Instrument
from .services.quote_fetcher import pull_single_instrument_quote
from .tasks import WATCHLIST_QUOTES_KEY, WATCHLIST_QUOTES_MARKET_KEY_PREFIX, UTC8

WATCHLIST_QUOTES_ORPHAN_KEY_PREFIX = "watchlist:quotes:orphan:"
DEFAULT_WATCHLIST_ORPHAN_TTL = 30 * 60


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



def _normalize_code(value: object) -> str:
    return str(value or "").strip().upper()


def _strip_market_suffix(symbol: object) -> str:
    s = _normalize_code(symbol)
    if "." not in s:
        return s
    return s.rsplit(".", 1)[0]


def _orphan_quote_cache_key(market: object, short_code: object) -> str:
    market_code = _normalize_code(market)
    code = _normalize_code(short_code)
    return f"{WATCHLIST_QUOTES_ORPHAN_KEY_PREFIX}{market_code}:{code}"


def _watchlist_orphan_ttl() -> int:
    raw = getattr(settings, "WATCHLIST_ORPHAN_QUOTE_TTL", DEFAULT_WATCHLIST_ORPHAN_TTL)
    try:
        ttl = int(raw)
    except (TypeError, ValueError):
        ttl = DEFAULT_WATCHLIST_ORPHAN_TTL
    return max(60, ttl)


class MarketQuoteSerializer(serializers.Serializer):
    short_code = serializers.CharField()
    name = serializers.CharField(allow_blank=True, required=False)
    prev_close = serializers.FloatField(required=False, allow_null=True)
    day_high = serializers.FloatField(required=False, allow_null=True)
    day_low = serializers.FloatField(required=False, allow_null=True)
    price = serializers.FloatField(required=False, allow_null=True)
    pct = serializers.FloatField(required=False, allow_null=True)
    volume = serializers.FloatField(required=False, allow_null=True)


class UserMarketBucketSerializer(serializers.Serializer):
    market = serializers.CharField()
    stale = serializers.BooleanField()
    quotes = MarketQuoteSerializer(many=True)


class UserMarketsSnapshotSerializer(serializers.Serializer):
    updated_at = serializers.CharField(allow_blank=True, allow_null=True, required=False)
    markets = UserMarketBucketSerializer(many=True)

    def to_representation(self, instance):
        payload = instance if isinstance(instance, dict) else {}
        data = payload.get("data")
        market_data = data if isinstance(data, dict) else {}
        stale_markets = {
            str(m).strip().upper()
            for m in (payload.get("stale_markets") or [])
            if isinstance(m, str)
        }

        request = self.context.get("request")
        user = getattr(request, "user", None)
        watchlist_codes = self._watchlist_codes_by_market(user)

        markets = []
        for market in sorted(watchlist_codes.keys()):
            allow_codes = watchlist_codes[market]
            raw_quotes = market_data.get(market, [])
            quotes = self._filter_quotes(raw_quotes, allow_codes)
            markets.append({
                "market": market,
                "stale": market in stale_markets,
                "quotes": MarketQuoteSerializer(quotes, many=True).data,
            })

        return {
            "updated_at": payload.get("updated_at"),
            "markets": markets,
        }

    def _watchlist_codes_by_market(self, user):
        if not user or not getattr(user, "is_authenticated", False):
            return {}

        grouped = {}
        rows = (
            WatchlistItem.objects
            .filter(user=user)
            .values_list("instrument__market", "instrument__short_code", "instrument__symbol")
        )

        for market, short_code, symbol in rows:
            m = _normalize_code(market)
            code = _normalize_code(short_code) or _strip_market_suffix(symbol)
            if not m or not code:
                continue
            grouped.setdefault(m, set()).add(code)

        return grouped

    def _filter_quotes(self, rows, allow_codes):
        if not isinstance(rows, list):
            return []

        filtered = []
        for row in rows:
            if not isinstance(row, dict):
                continue
            code = _normalize_code(row.get("short_code")) or _strip_market_suffix(row.get("symbol"))
            if code in allow_codes:
                filtered.append(row)
        return filtered


class InstrumentSearchItemSerializer(serializers.ModelSerializer):
    class Meta:
        model = Instrument
        fields = ["symbol", "short_code", "name", "market"]


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


class MarketWatchlistAddSerializer(serializers.Serializer):
    symbol = serializers.CharField()

    @staticmethod
    def _safe_payload_data(payload: object) -> dict:
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _find_quote_by_code(rows: object, short_code: str) -> dict | None:
        if not isinstance(rows, list):
            return None
        code = _normalize_code(short_code)
        for row in rows:
            if not isinstance(row, dict):
                continue
            if _normalize_code(row.get("short_code")) == code:
                return row
        return None

    @staticmethod
    def _upsert_market_quote(data: dict, market: str, quote_row: dict) -> None:
        market_rows = data.setdefault(market, [])
        if not isinstance(market_rows, list):
            market_rows = []
            data[market] = market_rows

        code = _normalize_code(quote_row.get("short_code"))
        for idx, row in enumerate(market_rows):
            if isinstance(row, dict) and _normalize_code(row.get("short_code")) == code:
                market_rows[idx] = quote_row
                return

        market_rows.append(quote_row)

    @staticmethod
    def _write_snapshot_to_cache(payload: dict, data: dict, updated_market: str) -> None:
        updated_at = timezone.now().astimezone(UTC8).isoformat()
        updated_markets = {
            _normalize_code(m)
            for m in (payload.get("updated_markets") or [])
            if isinstance(m, str)
        }
        updated_markets.add(updated_market)

        stale_markets = [
            m for m in (payload.get("stale_markets") or [])
            if _normalize_code(m) != updated_market
        ]

        next_payload = dict(payload) if isinstance(payload, dict) else {}
        next_payload.update(
            {
                "updated_at": updated_at,
                "updated_markets": sorted(updated_markets),
                "stale_markets": stale_markets,
                "data": data,
            }
        )

        timeout = None
        cache.set(WATCHLIST_QUOTES_KEY, next_payload, timeout=timeout)
        cache.set(
            f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{updated_market}",
            {
                "updated_at": updated_at,
                "market": updated_market,
                "stale": False,
                "data": data.get(updated_market, []),
            },
            timeout=timeout,
        )

    def validate_symbol(self, value):
        symbol = _normalize_code(value)
        if not symbol:
            raise serializers.ValidationError("symbol 不能为空")
        return symbol

    def validate(self, attrs):
        symbol = attrs["symbol"]
        instrument = (
            Instrument.objects
            .filter(symbol__iexact=symbol, is_active=True)
            .only("id", "symbol", "short_code", "name", "market")
            .first()
        )
        if instrument is None:
            raise serializers.ValidationError({"symbol": "未找到可用股票代码"})
        attrs["instrument"] = instrument
        return attrs

    def create(self, validated_data):
        request = self.context.get("request")
        if request is None:
            raise serializers.ValidationError("request context required")

        instrument = validated_data["instrument"]
        watch_item, created = WatchlistItem.objects.get_or_create(
            user=request.user,
            instrument=instrument,
        )

        market = _normalize_code(instrument.market)
        short_code = _normalize_code(instrument.short_code)

        payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
        data = self._safe_payload_data(payload)
        market_rows = data.get(market, [])
        existing_quote = self._find_quote_by_code(market_rows, short_code)

        quote_source = "redis" if existing_quote else "api"
        quote_ready = existing_quote is not None

        if existing_quote is None:
            orphan_key = _orphan_quote_cache_key(market, short_code)
            orphan_quote = cache.get(orphan_key)
            if isinstance(orphan_quote, dict):
                one_quote = dict(orphan_quote)
                one_quote["short_code"] = one_quote.get("short_code") or instrument.short_code
                one_quote["name"] = one_quote.get("name") or instrument.name
                self._upsert_market_quote(data, market, one_quote)
                self._write_snapshot_to_cache(payload, data, market)
                cache.delete(orphan_key)
                quote_source = "redis_orphan"
                quote_ready = True
            else:
                one_quote = pull_single_instrument_quote(
                    symbol=instrument.symbol,
                    short_code=instrument.short_code,
                    name=instrument.name,
                    market=market,
                )
                if one_quote:
                    one_quote["short_code"] = one_quote.get("short_code") or instrument.short_code
                    one_quote["name"] = one_quote.get("name") or instrument.name
                    self._upsert_market_quote(data, market, one_quote)
                    self._write_snapshot_to_cache(payload, data, market)
                    quote_ready = True
                else:
                    quote_source = "none"

        return {
            "created": created,
            "watchlist_item_id": watch_item.id,
            "instrument": {
                "symbol": instrument.symbol,
                "short_code": instrument.short_code,
                "name": instrument.name,
                "market": market,
            },
            "quote_ready": quote_ready,
            "quote_source": quote_source,
        }


class MarketWatchlistDeleteSerializer(serializers.Serializer):
    symbol = serializers.CharField(required=False, allow_blank=True)
    market = serializers.CharField(required=False, allow_blank=True)
    short_code = serializers.CharField(required=False, allow_blank=True)

    @staticmethod
    def _safe_payload_data(payload: object) -> dict:
        if not isinstance(payload, dict):
            return {}
        data = payload.get("data")
        return data if isinstance(data, dict) else {}

    @staticmethod
    def _write_snapshot_to_cache(payload: dict, data: dict, updated_markets: set[str]) -> None:
        if not updated_markets:
            return

        updated_at = timezone.now().astimezone(UTC8).isoformat()
        existing_updated = {
            _normalize_code(m)
            for m in (payload.get("updated_markets") or [])
            if isinstance(m, str)
        }
        existing_updated.update(updated_markets)

        stale_markets = [
            m for m in (payload.get("stale_markets") or [])
            if _normalize_code(m) not in updated_markets
        ]

        next_payload = dict(payload) if isinstance(payload, dict) else {}
        next_payload.update(
            {
                "updated_at": updated_at,
                "updated_markets": sorted(existing_updated),
                "stale_markets": stale_markets,
                "data": data,
            }
        )

        timeout = None
        cache.set(WATCHLIST_QUOTES_KEY, next_payload, timeout=timeout)

        for market in updated_markets:
            rows = data.get(market, [])
            market_key = f"{WATCHLIST_QUOTES_MARKET_KEY_PREFIX}{market}"
            if rows:
                cache.set(
                    market_key,
                    {
                        "updated_at": updated_at,
                        "market": market,
                        "stale": False,
                        "data": rows,
                    },
                    timeout=timeout,
                )
            else:
                cache.delete(market_key)

    @staticmethod
    def _pop_quote_by_code(data: dict, market: str, short_code: str) -> dict | None:
        rows = data.get(market, [])
        if not isinstance(rows, list):
            return None

        code = _normalize_code(short_code)
        kept = []
        removed_row = None
        for row in rows:
            if not isinstance(row, dict):
                continue
            row_code = _normalize_code(row.get("short_code")) or _strip_market_suffix(row.get("symbol"))
            if row_code == code:
                if removed_row is None:
                    removed_row = row
                continue
            kept.append(row)

        if removed_row is None:
            return None

        if kept:
            data[market] = kept
        else:
            data.pop(market, None)
        return removed_row

    def validate(self, attrs):
        request = self.context.get("request")
        if request is None:
            raise serializers.ValidationError("request context required")

        symbol = _normalize_code(attrs.get("symbol"))
        market = _normalize_code(attrs.get("market"))
        short_code = _normalize_code(attrs.get("short_code"))

        if not symbol and not (market and short_code):
            raise serializers.ValidationError("请提供 symbol，或同时提供 market + short_code")

        qs = WatchlistItem.objects.filter(user=request.user).select_related("instrument")
        if symbol:
            qs = qs.filter(instrument__symbol__iexact=symbol)
        else:
            qs = qs.filter(
                instrument__market__iexact=market,
                instrument__short_code__iexact=short_code,
            )

        items = list(qs)
        if not items:
            raise serializers.ValidationError("该标的不在你的自选中")

        attrs["watch_items"] = items
        return attrs

    def create(self, validated_data):
        items = validated_data["watch_items"]
        item_ids = [x.id for x in items]
        instruments = {}
        for item in items:
            inst = item.instrument
            instruments[inst.id] = inst

        WatchlistItem.objects.filter(id__in=item_ids).delete()

        payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
        data = self._safe_payload_data(payload)
        updated_markets: set[str] = set()

        for inst in instruments.values():
            # 仍有其他用户关注，不从 Redis 快照移除
            if WatchlistItem.objects.filter(instrument_id=inst.id).exists():
                continue

            market = _normalize_code(inst.market)
            short_code = _normalize_code(inst.short_code)
            removed_quote = self._pop_quote_by_code(data, market, short_code)
            if removed_quote is not None:
                updated_markets.add(market)
                cache.set(
                    _orphan_quote_cache_key(market, short_code),
                    removed_quote,
                    timeout=_watchlist_orphan_ttl(),
                )

        self._write_snapshot_to_cache(payload, data, updated_markets)

        return {
            "deleted": len(item_ids),
            "updated_markets": sorted(updated_markets),
        }
