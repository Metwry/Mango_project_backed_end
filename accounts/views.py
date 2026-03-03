from django_filters import rest_framework as filters
from rest_framework import filters as drf_filters, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Accounts, Transaction
from .pagination import TransactionPagination
from .services import reverse_transaction
from .serializers import AccountSerializer, TransactionSerializer


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
        reverse_tx = reverse_transaction(user=request.user, tx_id=int(pk))
        return Response(self.get_serializer(reverse_tx).data, status=status.HTTP_201_CREATED)
