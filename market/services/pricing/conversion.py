from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

from .fx import get_usd_base_fx_snapshot

TWOPLACES = Decimal("0.01")


def _to_decimal(value: str | int | float | Decimal) -> Decimal:
    return Decimal(str(value))


def _normalize_currency(value: str) -> str:
    return str(value or "").strip().upper()


def convert_currency(*, amounts: list[dict], base_currency: str) -> dict:
    target_currency = _normalize_currency(base_currency)
    if not target_currency:
        raise ValueError("base_currency is required")

    fx_snapshot = get_usd_base_fx_snapshot()
    rates = {
        code: _to_decimal(rate)
        for code, rate in fx_snapshot["rates"].items()
    }
    if target_currency not in rates:
        raise ValueError(f"unsupported base currency: {target_currency}")

    items: list[dict] = []
    for row in amounts:
        allowed_keys = {"key", "amount", "currency"}
        extra_keys = set(row.keys()) - allowed_keys
        if extra_keys:
            raise ValueError(f"unsupported fields in amount item: {sorted(extra_keys)}")

        key = str(row["key"])
        amount = _to_decimal(row["amount"])
        source_currency = _normalize_currency(row["currency"])
        if source_currency not in rates:
            raise ValueError(f"unsupported source currency: {source_currency}")

        if source_currency == target_currency:
            converted_amount = amount
        else:
            amount_in_usd = amount / rates[source_currency]
            converted_amount = amount_in_usd * rates[target_currency]

        items.append(
            {
                "key": key,
                "converted_amount": str(
                    converted_amount.quantize(TWOPLACES, rounding=ROUND_HALF_UP)
                ),
            }
        )

    return {
        "base_currency": target_currency,
        "items": items,
    }
