from __future__ import annotations

from market.services.pricing import convert_currency as convert_currency_by_market


def convert_currency(*, amounts: list[dict], base_currency: str) -> dict:
    return convert_currency_by_market(amounts=amounts, base_currency=base_currency)
