from rest_framework import status
from rest_framework.exceptions import ValidationError
from rest_framework.response import Response
from rest_framework.views import APIView
from common.utils import normalize_code

from .serializers import (
    InstrumentSearchQuerySerializer,
    InstrumentSearchItemSerializer,
    LatestQuoteBatchSerializer,
)
from .services.api.service import (
    add_watchlist_symbol,
    build_latest_quotes,
    build_user_markets_snapshot,
    delete_watchlist_symbol,
    search_instruments,
)
from .services.data.indices import pull_indices
from .services.data.rates import get_fx_rates

class MarketsView(APIView):
    # ed 返回当前用户自选市场的最新行情数据。
    def get(self, request, *args, **kwargs):
        return Response(build_user_markets_snapshot(request.user), status=status.HTTP_200_OK)


class MarketFxRatesView(APIView):
    # ed 返回指定基准货币对应的汇率行情数据。
    def get(self, request, *args, **kwargs):
        try:
            payload = get_fx_rates(request.query_params.get("base"))
        except ValueError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(payload, status=status.HTTP_200_OK)


class MarketInstrumentSearchView(APIView):
    # ed 根据关键词搜索可交易标的。
    def get(self, request, *args, **kwargs):
        params = InstrumentSearchQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        if not params.validated_data["query"]:
            return Response({"results": []}, status=status.HTTP_200_OK)

        qs = search_instruments(
            query=params.validated_data["query"],
            limit=params.validated_data["limit"],
        )
        serializer = InstrumentSearchItemSerializer(qs, many=True)
        return Response({"results": serializer.data}, status=status.HTTP_200_OK)


class MarketLatestQuoteBatchView(APIView):
    # ed 批量返回持仓标的的最新价格数据。
    def post(self, request, *args, **kwargs):
        serializer = LatestQuoteBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quotes = build_latest_quotes(serializer.validated_data["items"])
        return Response({"quotes": quotes}, status=status.HTTP_200_OK)


class MarketIndexSnapshotView(APIView):
    # ed 返回核心指数行情快照。
    def get(self, request, *args, **kwargs):
        return Response(pull_indices(), status=status.HTTP_200_OK)


class MarketWatchlistAddView(APIView):
    # ed 将指定标的加入当前用户自选。
    def post(self, request, *args, **kwargs):
        symbol = str(request.data.get("symbol") or "").strip()
        if not symbol:
            raise ValidationError({"symbol": "symbol 不能为空"})
        result = add_watchlist_symbol(
            user=request.user,
            symbol=symbol,
        )

        status_code = status.HTTP_201_CREATED if result.get("created") else status.HTTP_200_OK
        return Response(result, status=status_code)

    # ed 将指定标的从当前用户自选移除，并同步更新缓存行情。
    def delete(self, request, *args, **kwargs):
        market = normalize_code(request.data.get("market"))
        short_code = normalize_code(request.data.get("short_code"))
        errors = {}
        if not market:
            errors["market"] = "market 不能为空"
        if not short_code:
            errors["short_code"] = "short_code 不能为空"
        if errors:
            raise ValidationError(errors)
        result = delete_watchlist_symbol(
            user=request.user,
            market=market,
            short_code=short_code,
        )
        return Response(result, status=status.HTTP_200_OK)
