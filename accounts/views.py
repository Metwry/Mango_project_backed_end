from decimal import Decimal

from django.core.cache import cache
from django.db import transaction as db_transaction
from django.utils import timezone
from django_filters import rest_framework as filters
from rest_framework import viewsets, filters as drf_filters, status
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Accounts, Transaction
from .pagination import TransactionPagination
from .services.quote_fetcher import pull_usd_exchange_rates
from .serializers import (
    AccountSerializer,
    InstrumentSearchItemSerializer,
    MarketInstrumentSearchQuerySerializer,
    MarketWatchlistAddSerializer,
    MarketWatchlistDeleteSerializer,
    TransactionSerializer,
    UserMarketsSnapshotSerializer,
)
from .tasks import WATCHLIST_QUOTES_KEY, USD_EXCHANGE_RATES_KEY, UTC8


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        return Accounts.objects.filter(user=self.request.user).order_by("-balance")

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)


class TransactionFilter(filters.FilterSet):
    account_id = filters.NumberFilter(field_name="account")
    account_name = filters.CharFilter(field_name="account__name", lookup_expr="icontains")
    counterparty = filters.CharFilter(lookup_expr="icontains")
    category = filters.CharFilter(field_name="category_name", lookup_expr="icontains")
    start = filters.DateTimeFilter(field_name="add_date", lookup_expr="gte")
    end = filters.DateTimeFilter(field_name="add_date", lookup_expr="lte")

    class Meta:
        model = Transaction
        fields = ["currency"]


class TransactionViewSet(viewsets.ModelViewSet):
    serializer_class = TransactionSerializer
    permission_classes = [IsAuthenticated]
    pagination_class = TransactionPagination

    filter_backends = [filters.DjangoFilterBackend, drf_filters.SearchFilter, drf_filters.OrderingFilter]
    filterset_class = TransactionFilter
    search_fields = ["counterparty", "category_name"]
    ordering_fields = ["amount", "created_at", "add_date"]

    def get_queryset(self):
        qs = (
            Transaction.objects
            .select_related("account")
            .filter(user=self.request.user)
            .order_by("-add_date", "-id")
        )

        if self.action == "list":
            qs = qs.filter(reversal_of__isnull=True)
            if not self.request.query_params.get("include_reversed"):
                qs = qs.filter(reversed_at__isnull=True)

        return qs

    def perform_create(self, serializer):
        serializer.save(user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        raise ValidationError("不允许删除交易记录，请使用撤销功能。")

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        with db_transaction.atomic():
            tx = (
                Transaction.objects
                .select_for_update()
                .select_related("account")
                .get(pk=pk, user=request.user)
            )

            if tx.reversal_of_id is not None:
                raise ValidationError("撤销交易不能再次撤销。")
            if tx.reversed_at is not None:
                raise ValidationError("该交易已撤销，不能重复撤销。")

            reverse_tx = Transaction.objects.create(
                user=request.user,
                account=tx.account,
                counterparty=f"撤销: {tx.counterparty}",
                category_name="撤销",
                amount=Decimal("0") - (tx.amount or Decimal("0")),
                add_date=timezone.now(),
                reversal_of=tx,
            )

            tx.reversed_at = timezone.now()
            tx.save(update_fields=["reversed_at"])

            return Response(self.get_serializer(reverse_tx).data, status=status.HTTP_201_CREATED)


class MarketsView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
        serializer = UserMarketsSnapshotSerializer(payload, context={"request": request})
        return Response(serializer.data, status=status.HTTP_200_OK)


class MarketFxRatesView(APIView):
    permission_classes = [IsAuthenticated]

    @staticmethod
    def _normalize_rates(raw_rates):
        if not isinstance(raw_rates, dict):
            return {"USD": 1.0}

        normalized = {}
        for code, raw in raw_rates.items():
            c = str(code or "").strip().upper()
            if not c:
                continue
            try:
                v = float(raw)
            except (TypeError, ValueError):
                continue
            if v > 0:
                normalized[c] = v

        normalized["USD"] = 1.0
        return normalized

    def get(self, request, *args, **kwargs):
        requested_base = str(request.query_params.get("base") or "USD").strip().upper()

        payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
        rates = self._normalize_rates(payload.get("rates") if isinstance(payload, dict) else None)
        updated_at = payload.get("updated_at") if isinstance(payload, dict) else None

        if len(rates) <= 1:
            watch_payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
            snapshot_data = watch_payload.get("data") if isinstance(watch_payload, dict) else {}
            fx_rows = snapshot_data.get("FX") if isinstance(snapshot_data, dict) else []
            if not isinstance(fx_rows, list):
                fx_rows = []

            rates = pull_usd_exchange_rates(seed_rows=fx_rows)
            updated_at = timezone.now().astimezone(UTC8).isoformat()
            cache.set(
                USD_EXCHANGE_RATES_KEY,
                {"base": "USD", "updated_at": updated_at, "rates": rates},
                timeout=None,
            )

        if requested_base not in rates:
            return Response(
                {"detail": f"unsupported base currency: {requested_base}"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if requested_base == "USD":
            final_rates = rates
        else:
            base_usd_rate = rates[requested_base]
            final_rates = {code: (usd_rate / base_usd_rate) for code, usd_rate in rates.items()}
            final_rates[requested_base] = 1.0

        return Response(
            {
                "base": requested_base,
                "updated_at": updated_at,
                "rates": final_rates,
            },
            status=status.HTTP_200_OK,
        )


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


class MarketWatchlistAddView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = MarketWatchlistAddSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()

        status_code = status.HTTP_201_CREATED if result.get("created") else status.HTTP_200_OK
        return Response(result, status=status_code)

    def delete(self, request, *args, **kwargs):
        serializer = MarketWatchlistDeleteSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
