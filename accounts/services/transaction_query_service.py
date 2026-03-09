from rest_framework.exceptions import ValidationError

from accounts.models import Transaction

ACTIVITY_MANUAL = "manual"
ACTIVITY_INVESTMENT = "investment"
ACTIVITY_TRANSFER = "transfer"
ACTIVITY_REVERSED = "reversed"
VALID_ACTIVITY_TYPES = {ACTIVITY_MANUAL, ACTIVITY_INVESTMENT, ACTIVITY_TRANSFER, ACTIVITY_REVERSED}


def _parse_activity_type(query_params) -> str:
    raw = str(query_params.get("activity_type", ACTIVITY_MANUAL)).strip().lower()
    if raw not in VALID_ACTIVITY_TYPES:
        raise ValidationError(
            {
                "activity_type": "仅支持 manual / investment / transfer / reversed",
            }
        )
    return raw


def build_transaction_queryset(*, user, action: str, query_params):
    queryset = (
        Transaction.objects
        .select_related("account")
        .filter(user=user)
        .order_by("-add_date", "-id")
    )

    if action != "list":
        return queryset

    queryset = queryset.filter(reversal_of__isnull=True)
    activity_type = _parse_activity_type(query_params)

    if activity_type == ACTIVITY_INVESTMENT:
        return queryset.filter(source=Transaction.Source.INVESTMENT, reversed_at__isnull=True)
    if activity_type == ACTIVITY_TRANSFER:
        return queryset.filter(source=Transaction.Source.TRANSFER, reversed_at__isnull=True)
    if activity_type == ACTIVITY_REVERSED:
        return queryset.filter(reversed_at__isnull=False)
    return queryset.filter(source=Transaction.Source.MANUAL, reversed_at__isnull=True)
