from django.db.models import Case, IntegerField, Q, Value, When

from market.models import Instrument


# 根据代码或名称搜索当前可交易的标的列表。
def search_instruments(*, query: str, query_upper: str, limit: int):
    if not query:
        return Instrument.objects.none()

    return (
        Instrument.objects
        .filter(is_active=True)
        .filter(
            Q(short_code__icontains=query_upper)
            | Q(name__icontains=query)
        )
        .annotate(
            priority=Case(
                When(short_code__iexact=query_upper, then=Value(0)),
                When(short_code__istartswith=query_upper, then=Value(1)),
                When(name__istartswith=query, then=Value(2)),
                default=Value(3),
                output_field=IntegerField(),
            )
        )
        .order_by("priority", "short_code", "name")[:limit]
    )
