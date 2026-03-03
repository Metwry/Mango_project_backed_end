import logging
from time import perf_counter

from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView
from shared.logging_utils import log_info

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
    build_user_markets_snapshot,
    delete_watchlist_symbol,
    get_fx_rates,
)

logger = logging.getLogger(__name__)


class MarketsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        return Response(build_user_markets_snapshot(request.user), status=status.HTTP_200_OK)


class MarketFxRatesView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        try:
            payload = get_fx_rates(request.query_params.get("base"))
        except ValueError as exc:
            return Response(
                {"detail": str(exc)},
                status=status.HTTP_400_BAD_REQUEST,
            )
        return Response(payload, status=status.HTTP_200_OK)


class MarketInstrumentSearchView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        params = MarketInstrumentSearchQuerySerializer(data=request.query_params)
        params.is_valid(raise_exception=True)

        if not params.validated_data["query"]:
            return Response({"results": []}, status=status.HTTP_200_OK)

        qs = params.build_queryset()
        serializer = InstrumentSearchItemSerializer(qs, many=True)
        return Response({"results": serializer.data}, status=status.HTTP_200_OK)


class MarketLatestQuoteBatchView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = MarketLatestQuoteBatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        quotes = build_latest_quotes(serializer.validated_data["items"])
        return Response({"quotes": quotes}, status=status.HTTP_200_OK)


class MarketWatchlistAddView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        started = perf_counter()
        user_id = getattr(request.user, "id", None)
        request_symbol = request.data.get("symbol")
        log_info(
            logger,
            "api.watchlist.add.request",
            user_id=user_id,
            symbol=request_symbol,
        )
        serializer = MarketWatchlistAddSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = add_watchlist_symbol(
            user=request.user,
            symbol=serializer.validated_data["symbol"],
        )

        status_code = status.HTTP_201_CREATED if result.get("created") else status.HTTP_200_OK
        elapsed_ms = int((perf_counter() - started) * 1000)
        instrument = result.get("instrument") or {}
        log_info(
            logger,
            "api.watchlist.add.response",
            user_id=user_id,
            status=status_code,
            elapsed_ms=elapsed_ms,
            created=result.get("created"),
            symbol=instrument.get("symbol"),
            short_code=instrument.get("short_code"),
            market=instrument.get("market"),
            quote_ready=result.get("quote_ready"),
            quote_source=result.get("quote_source"),
        )
        return Response(result, status=status_code)

    def delete(self, request, *args, **kwargs):
        started = perf_counter()
        user_id = getattr(request.user, "id", None)
        log_info(
            logger,
            "api.watchlist.delete.request",
            user_id=user_id,
            symbol=request.data.get("symbol"),
            market=request.data.get("market"),
            short_code=request.data.get("short_code"),
        )
        serializer = MarketWatchlistDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = delete_watchlist_symbol(
            user=request.user,
            symbol=serializer.validated_data.get("symbol", ""),
            market=serializer.validated_data.get("market", ""),
            short_code=serializer.validated_data.get("short_code", ""),
        )
        elapsed_ms = int((perf_counter() - started) * 1000)
        log_info(
            logger,
            "api.watchlist.delete.response",
            user_id=user_id,
            status=status.HTTP_200_OK,
            elapsed_ms=elapsed_ms,
            deleted=result.get("deleted"),
            updated_markets=result.get("updated_markets"),
        )
        return Response(result, status=status.HTTP_200_OK)
