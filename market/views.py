from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    FxRatesQueryRequestSerializer,
    FxRatesResponseSerializer,
    IndexSnapshotResponseSerializer,
    InstrumentSearchQueryRequestSerializer,
    InstrumentSearchResponseSerializer,
    LatestQuoteBatchRequestSerializer,
    LatestQuoteBatchResponseSerializer,
    MarketSnapshotResponseSerializer,
    WatchlistAddRequestSerializer,
    WatchlistAddResponseSerializer,
    WatchlistDeleteRequestSerializer,
    WatchlistDeleteResponseSerializer,
)
from .services.data.index_snapshot import pull_indices
from .services.fx_rates import get_fx_rates
from .services.instrument_queries import build_latest_quotes, build_user_markets_snapshot, search_instruments
from .services.instrument_subscriptions import add_watchlist_symbol, delete_watchlist_symbol


class MarketWatchlistSnapshotView(APIView):
    # ed 返回当前用户自选市场的最新行情数据。
    def get(self, request, *args, **kwargs):
        payload = build_user_markets_snapshot(request.user)
        serializer = MarketSnapshotResponseSerializer(instance=payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MarketFxRatesView(APIView):
    # ed 返回指定基准货币对应的汇率行情数据。
    def get(self, request, *args, **kwargs):
        request_serializer = FxRatesQueryRequestSerializer(data=request.query_params)
        request_serializer.is_valid(raise_exception=True)
        try:
            payload = get_fx_rates(request_serializer.validated_data["base"])
        except ValueError as exc:
            return Response(
                {"message": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        response_serializer = FxRatesResponseSerializer(instance=payload)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class MarketInstrumentSearchView(APIView):
    # ed 根据关键词搜索可交易标的。
    def get(self, request, *args, **kwargs):
        request_serializer = InstrumentSearchQueryRequestSerializer(data=request.query_params)
        request_serializer.is_valid(raise_exception=True)
        query = request_serializer.validated_data["query"]
        if not query:
            payload = {"results": []}
        else:
            payload = {
                "results": list(
                    search_instruments(
                        query=query,
                        limit=request_serializer.validated_data["limit"],
                    )
                )
            }
        response_serializer = InstrumentSearchResponseSerializer(instance=payload)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class MarketLatestQuoteBatchView(APIView):
    # ed 批量返回持仓标的的最新价格数据。
    def post(self, request, *args, **kwargs):
        request_serializer = LatestQuoteBatchRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = {"quotes": build_latest_quotes(request_serializer.validated_data["items"])}
        response_serializer = LatestQuoteBatchResponseSerializer(instance=payload)
        return Response(response_serializer.data, status=status.HTTP_200_OK)


class MarketIndexSnapshotView(APIView):
    # ed 返回核心指数行情快照。
    def get(self, request, *args, **kwargs):
        payload = pull_indices()
        serializer = IndexSnapshotResponseSerializer(instance=payload)
        return Response(serializer.data, status=status.HTTP_200_OK)


class MarketWatchlistView(APIView):
    # ed 将指定标的加入当前用户自选。
    def post(self, request, *args, **kwargs):
        request_serializer = WatchlistAddRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = add_watchlist_symbol(
            user=request.user,
            symbol=request_serializer.validated_data["symbol"],
        )
        response_serializer = WatchlistAddResponseSerializer(instance=payload)
        status_code = status.HTTP_201_CREATED if payload.get("created") else status.HTTP_200_OK
        return Response(response_serializer.data, status=status_code)

    # ed 将指定标的从当前用户自选移除，并同步更新缓存行情。
    def delete(self, request, *args, **kwargs):
        request_serializer = WatchlistDeleteRequestSerializer(data=request.data)
        request_serializer.is_valid(raise_exception=True)
        payload = delete_watchlist_symbol(
            user=request.user,
            market=request_serializer.validated_data["market"],
            short_code=request_serializer.validated_data["short_code"],
        )
        response_serializer = WatchlistDeleteResponseSerializer(instance=payload)
        return Response(response_serializer.data, status=status.HTTP_200_OK)
