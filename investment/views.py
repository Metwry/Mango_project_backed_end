from rest_framework import status
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from .models import Position
from .serializers import (
    InvestmentBuySerializer,
    InvestmentSellSerializer,
    PositionDeleteSerializer,
    PositionListItemSerializer,
)


class InvestmentBuyView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = InvestmentBuySerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)


class InvestmentSellView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request, *args, **kwargs):
        serializer = InvestmentSellSerializer(data=request.data, context={"request": request})
        serializer.is_valid(raise_exception=True)
        result = serializer.save()
        return Response(result, status=status.HTTP_201_CREATED)


class InvestmentPositionListView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        queryset = (
            Position.objects
            .filter(user=request.user, quantity__gt=0)
            .select_related("instrument")
            .only(
                "instrument_id",
                "quantity",
                "avg_cost",
                "cost_total",
                "instrument__symbol",
                "instrument__short_code",
                "instrument__name",
                "instrument__market",
            )
            .order_by("instrument__symbol")
        )
        serializer = PositionListItemSerializer(queryset, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)


class InvestmentPositionDeleteView(APIView):
    permission_classes = [IsAuthenticated]

    def delete(self, request, instrument_id: int, *args, **kwargs):
        serializer = PositionDeleteSerializer(context={"request": request, "instrument_id": instrument_id})
        result = serializer.save()
        return Response(result, status=status.HTTP_200_OK)
