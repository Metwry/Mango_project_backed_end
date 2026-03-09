from investment.models import Position


def build_position_list_queryset(*, user):
    return (
        Position.objects
        .filter(user=user, quantity__gt=0)
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


def query_investment_history(*, user, params: dict):
    queryset = (
        user.investment_records
        .select_related("instrument", "cash_account", "cash_transaction")
        .order_by("-trade_at", "-id")
    )
    if params.get("account_id") is not None:
        queryset = queryset.filter(cash_account_id=params["account_id"])
    if params.get("instrument_id") is not None:
        queryset = queryset.filter(instrument_id=params["instrument_id"])
    if params.get("side") is not None:
        queryset = queryset.filter(side=params["side"])
    if params.get("start") is not None:
        queryset = queryset.filter(trade_at__gte=params["start"])
    if params.get("end") is not None:
        queryset = queryset.filter(trade_at__lte=params["end"])

    total = queryset.count()
    offset = params["offset"]
    limit = params["limit"]
    rows = list(queryset[offset: offset + limit])
    return {
        "count": total,
        "offset": offset,
        "limit": limit,
        "rows": rows,
    }
