from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    InstrumentSearchItemSerializer,
    MarketInstrumentSearchQuerySerializer,
    MarketLatestQuoteBatchSerializer,
    MarketWatchlistAddSerializer,
    MarketWatchlistDeleteSerializer,
)
from .services import (
    add_watchlist_symbol,
    build_latest_quotes,
    build_market_indices_snapshot,
    build_user_markets_snapshot,
    delete_watchlist_symbol,
    get_fx_rates,
    search_instruments,
)

class MarketsView(APIView):
    permission_classes = [IsAuthenticated]

    # 返回当前用户自选市场的最新行情行情数据。
    def get(self, request, *args, **kwargs):
        return Response(build_user_markets_snapshot(request.user), status=status.HTTP_200_OK)


class MarketFxRatesView(APIView):
    permission_classes = [IsAuthenticated]

    # 返回指定基准货币对应的汇率行情数据。
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
    permission_classes = [IsAuthenticated]

    # 根据关键词搜索可交易标的。
    def get(self, request, *args, **kwargs):
        params = MarketInstrumentSearchQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        if not params.validated_data["query"]:
            return Response({"results": []}, status=status.HTTP_200_OK)

        qs = search_instruments(
            query=params.validated_data["query"],
            query_upper=params.validated_data["query_upper"],
            limit=params.validated_data["limit"],
        )
        serializer = InstrumentSearchItemSerializer(qs, many=True)
        return Response({"results": serializer.data}, status=status.HTTP_200_OK)


class MarketLatestQuoteBatchView(APIView):
    permission_classes = [IsAuthenticated]

    # 批量返回多个标的的最新价格摘要。
    def post(self, request, *args, **kwargs):
        serializer = MarketLatestQuoteBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quotes = build_latest_quotes(serializer.validated_data["items"])
        return Response({"quotes": quotes}, status=status.HTTP_200_OK)


class MarketIndexSnapshotView(APIView):
    permission_classes = [IsAuthenticated]

    # 返回核心指数行情快照。
    def get(self, request, *args, **kwargs):
        return Response(build_market_indices_snapshot(), status=status.HTTP_200_OK)


class MarketWatchlistAddView(APIView):
    permission_classes = [IsAuthenticated]

    # 将指定标的加入当前用户自选。
    def post(self, request, *args, **kwargs):
        serializer = MarketWatchlistAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = add_watchlist_symbol(
            user=request.user,
            symbol=serializer.validated_data["symbol"],
        )

        status_code = status.HTTP_201_CREATED if result.get("created") else status.HTTP_200_OK
        return Response(result, status=status_code)

    # 将指定标的从当前用户自选移除，并同步更新缓存行情。
    def delete(self, request, *args, **kwargs):
        serializer = MarketWatchlistDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = delete_watchlist_symbol(
            user=request.user,
            symbol=serializer.validated_data.get("symbol", ""),
            market=serializer.validated_data.get("market", ""),
            short_code=serializer.validated_data.get("short_code", ""),
        )
        return Response(result, status=status.HTTP_200_OK)
