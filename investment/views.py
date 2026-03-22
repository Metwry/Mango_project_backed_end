from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView

from .serializers import (
    HistoryQuerySerializer,
    PositionListItemSerializer,
    TradeSerializer,
    InvestmentHistoryItemSerializer,
)
from .services.query_service import build_position_list_queryset, query_investment_history
from .services.trade_service import execute_buy, execute_sell



class InvestmentBuyView(APIView):
    # ed 执行买入交易并返回持仓与资金流水结果。
    def post(self, request, *args, **kwargs):
        serializer = TradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = execute_buy(user=request.user, **serializer.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)


class InvestmentSellView(APIView):
    # ed 执行卖出交易并返回持仓、已实现盈亏与资金流水结果。
    def post(self, request, *args, **kwargs):
        serializer = TradeSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        result = execute_sell(user=request.user, **serializer.validated_data)
        return Response(result, status=status.HTTP_201_CREATED)


class InvestmentPositionListView(APIView):
    # ed 返回当前用户的有效持仓列表。
    def get(self, request, *args, **kwargs):
        queryset = build_position_list_queryset(user=request.user)
        serializer = PositionListItemSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class InvestmentHistoryListView(APIView):
    # 按筛选条件查询投资交易历史。
    def get(self, request, *args, **kwargs):
        query_serializer = HistoryQuerySerializer(data=request.query_params)
        query_serializer.is_valid(raise_exception=True)
        result = query_investment_history(user=request.user, params=query_serializer.validated_data)

        return Response(
            {
                "count": result["count"],
                "offset": result["offset"],
                "limit": result["limit"],
                "items": InvestmentHistoryItemSerializer(result["rows"], many=True).data,
            },
            status=status.HTTP_200_OK,
        )
