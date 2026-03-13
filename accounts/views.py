from django_filters import rest_framework as filters
from rest_framework import filters as drf_filters, mixins, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import ValidationError
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from .models import Transaction, Transfer
from .pagination import TransactionPagination
from .services import (
    archive_account,
    build_transaction_queryset,
    create_transfer,
    create_transaction_for_user,
    delete_single_transaction,
    delete_transactions_by_activity,
    get_transfer_for_user,
    get_user_accounts_queryset,
    reverse_transaction,
    reverse_transfer,
    should_include_archived,
    update_account_from_serializer,
)
from .serializers import (
    AccountSerializer,
    TransactionDeleteRequestSerializer,
    TransactionSerializer,
    TransferCreateSerializer,
    TransferSerializer,
)


class AccountViewSet(viewsets.ModelViewSet):
    serializer_class = AccountSerializer
    permission_classes = [IsAuthenticated]
    # ed
    def get_queryset(self):
        include_archived = should_include_archived(self.request.query_params.get("include_archived"))
        return get_user_accounts_queryset(user=self.request.user, include_archived=include_archived)

    def perform_update(self, serializer):
        serializer.instance = update_account_from_serializer(serializer=serializer)

    def destroy(self, request, *args, **kwargs):
        instance = self.get_object()
        conflict_payload = archive_account(account=instance, user=request.user)
        if conflict_payload:
            return Response(conflict_payload, status=status.HTTP_409_CONFLICT)
        return Response(status=status.HTTP_204_NO_CONTENT)

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
        return build_transaction_queryset(
            user=self.request.user,
            action=self.action,
            query_params=self.request.query_params,
        )

    def perform_create(self, serializer):
        create_transaction_for_user(serializer=serializer, user=self.request.user)

    def destroy(self, request, *args, **kwargs):
        result = delete_single_transaction(user=request.user, tx_id=int(kwargs.get("pk")))
        return Response(result, status=status.HTTP_200_OK)

    @action(detail=False, methods=["post"], url_path="delete")
    def delete_records(self, request):
        serializer = TransactionDeleteRequestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        params = serializer.validated_data

        if params["mode"] == "single":
            result = delete_single_transaction(
                user=request.user,
                tx_id=params["transaction_id"],
            )
            return Response(result, status=status.HTTP_200_OK)

        result = delete_transactions_by_activity(
            user=request.user,
            activity_type=params["activity_type"],
        )
        return Response(result, status=status.HTTP_200_OK)

    @staticmethod
    def _error_message(exc: ValidationError) -> str:
        detail = exc.detail
        if isinstance(detail, list):
            return str(detail[0]) if detail else "请求失败"
        if isinstance(detail, dict):
            first_value = next(iter(detail.values()), None)
            if isinstance(first_value, list):
                return str(first_value[0]) if first_value else "请求失败"
            if first_value is not None:
                return str(first_value)
            return "请求失败"
        return str(detail)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        try:
            reverse_result = reverse_transaction(user=request.user, tx_id=int(pk))
        except (TypeError, ValueError):
            return Response({"message": "交易ID格式不正确。"}, status=status.HTTP_400_BAD_REQUEST)
        except Transaction.DoesNotExist:
            return Response({"message": "交易不存在或无权限。"}, status=status.HTTP_404_NOT_FOUND)
        except ValidationError as exc:
            return Response({"message": self._error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)
        if isinstance(reverse_result, tuple) and reverse_result[0] == "transfer":
            return Response(TransferSerializer(reverse_result[1]).data, status=status.HTTP_201_CREATED)
        return Response(self.get_serializer(reverse_result).data, status=status.HTTP_201_CREATED)


class TransferViewSet(mixins.CreateModelMixin, mixins.ListModelMixin, mixins.RetrieveModelMixin, viewsets.GenericViewSet):
    permission_classes = [IsAuthenticated]
    serializer_class = TransferSerializer

    def get_queryset(self):
        return (
            Transfer.objects
            .select_related(
                "from_account",
                "to_account",
                "out_transaction",
                "in_transaction",
                "reversed_out_transaction",
                "reversed_in_transaction",
            )
            .filter(user=self.request.user)
            .order_by("-created_at", "-id")
        )

    def get_serializer_class(self):
        if self.action == "create":
            return TransferCreateSerializer
        return TransferSerializer

    def create(self, request, *args, **kwargs):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        transfer = create_transfer(user=request.user, **serializer.validated_data)
        return Response(TransferSerializer(transfer).data, status=status.HTTP_201_CREATED)

    @action(detail=True, methods=["post"])
    def reverse(self, request, pk=None):
        try:
            transfer = reverse_transfer(user=request.user, transfer_id=int(pk))
        except (TypeError, ValueError):
            return Response({"message": "转账ID格式不正确。"}, status=status.HTTP_400_BAD_REQUEST)
        except ValidationError as exc:
            return Response({"message": TransactionViewSet._error_message(exc)}, status=status.HTTP_400_BAD_REQUEST)
        transfer = get_transfer_for_user(user=request.user, transfer_id=transfer.id)
        return Response(TransferSerializer(transfer).data, status=status.HTTP_201_CREATED)
