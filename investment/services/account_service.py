from decimal import Decimal

from django.core.cache import cache
from django.db import IntegrityError, transaction

from accounts.models import Accounts, Currency
from market.services.cache_keys import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY
from shared.utils import normalize_code, quantize_decimal, strip_market_suffix, to_decimal, safe_payload_data

from ..models import Position

INVESTMENT_ACCOUNT_NAME = "投资账户"
POSITION_ZERO = Decimal("0")
ACCOUNT_PRECISION = Decimal("0.01")
MARKET_TO_CURRENCY = {
    "US": "USD",
    "CN": "CNY",
    "HK": "HKD",
    "CRYPTO": "USD",
    "FX": "USD",
}
def _quantize_account(value: Decimal) -> Decimal:
    return quantize_decimal(value, ACCOUNT_PRECISION)


def _build_quote_index() -> dict[tuple[str, str], Decimal]:
    payload = cache.get(WATCHLIST_QUOTES_KEY) or {}
    data = safe_payload_data(payload)
    quote_index: dict[tuple[str, str], Decimal] = {}

    for market, rows in data.items():
        market_code = normalize_code(market)
        if not market_code or not isinstance(rows, list):
            continue

        for row in rows:
            if not isinstance(row, dict):
                continue
            short_code = normalize_code(row.get("short_code")) or strip_market_suffix(row.get("symbol"))
            if not short_code:
                continue
            price = to_decimal(row.get("price"))
            if price is None or price <= 0:
                continue
            quote_index[(market_code, short_code)] = price

    return quote_index


def _load_usd_rates() -> dict[str, Decimal]:
    payload = cache.get(USD_EXCHANGE_RATES_KEY) or {}
    raw_rates = payload.get("rates") if isinstance(payload, dict) else None
    rates: dict[str, Decimal] = {"USD": Decimal("1")}
    if not isinstance(raw_rates, dict):
        return rates

    for code, raw_value in raw_rates.items():
        ccy = normalize_code(code)
        value = to_decimal(raw_value)
        if not ccy or value is None or value <= 0:
            continue
        rates[ccy] = value

    rates["USD"] = Decimal("1")
    return rates


def _expected_currency_for_position(position: Position) -> str:
    instrument = position.instrument
    base_currency = normalize_code(getattr(instrument, "base_currency", ""))
    if base_currency:
        return base_currency
    return MARKET_TO_CURRENCY.get(normalize_code(instrument.market), "")


def _convert_currency(amount: Decimal, from_currency: str, to_currency: str, usd_rates: dict[str, Decimal]) -> Decimal:
    source = normalize_code(from_currency)
    target = normalize_code(to_currency)
    if not source or not target or source == target:
        return amount

    source_rate = usd_rates.get(source)
    target_rate = usd_rates.get(target)
    if source_rate is None or target_rate is None or source_rate <= 0 or target_rate <= 0:
        return amount

    amount_in_usd = amount / source_rate
    return amount_in_usd * target_rate


def calculate_investment_account_balance(*, user, currency: str) -> Decimal:
    positions = list(
        Position.objects
        .filter(user=user, quantity__gt=0)
        .select_related("instrument")
        .only(
            "quantity",
            "avg_cost",
            "instrument__market",
            "instrument__short_code",
            "instrument__symbol",
            "instrument__base_currency",
        )
    )
    if not positions:
        return POSITION_ZERO

    quote_index = _build_quote_index()
    usd_rates = _load_usd_rates()
    target_currency = normalize_code(currency) or Currency.CNY

    total_value = POSITION_ZERO
    for position in positions:
        quantity = position.quantity or POSITION_ZERO
        if quantity <= 0:
            continue

        market = normalize_code(position.instrument.market)
        short_code = normalize_code(position.instrument.short_code) or strip_market_suffix(position.instrument.symbol)
        latest_price = quote_index.get((market, short_code))
        if latest_price is None:
            latest_price = position.avg_cost or POSITION_ZERO

        position_value = quantity * latest_price
        source_currency = _expected_currency_for_position(position) or target_currency
        converted = _convert_currency(position_value, source_currency, target_currency, usd_rates)
        total_value += converted

    if total_value <= 0:
        return POSITION_ZERO
    return _quantize_account(total_value)


def sync_investment_account_for_user(*, user, target_currency: str | None = None) -> Accounts | None:
    with transaction.atomic():
        account_qs = (
            Accounts.objects
            .select_for_update()
            .filter(
                user=user,
                type=Accounts.AccountType.INVESTMENT,
                name=INVESTMENT_ACCOUNT_NAME,
            )
            .order_by("id")
        )
        accounts = list(account_qs)
        account = accounts[0] if accounts else None
        for duplicate in accounts[1:]:
            duplicate.delete()

        has_positions = Position.objects.filter(user=user, quantity__gt=0).exists()
        if not has_positions:
            if account is not None:
                account.delete()
            return None

        desired_currency = normalize_code(target_currency) or (account.currency if account else Currency.CNY)
        if account is None:
            try:
                account = Accounts.objects.create(
                    user=user,
                    name=INVESTMENT_ACCOUNT_NAME,
                    type=Accounts.AccountType.INVESTMENT,
                    currency=desired_currency,
                    status=Accounts.Status.ACTIVE,
                    balance=POSITION_ZERO,
                )
            except IntegrityError:
                account = (
                    Accounts.objects
                    .select_for_update()
                    .filter(
                        user=user,
                        type=Accounts.AccountType.INVESTMENT,
                        name=INVESTMENT_ACCOUNT_NAME,
                    )
                    .order_by("id")
                    .first()
                )
                if account is None:
                    raise

        update_fields: list[str] = []
        if account.currency != desired_currency:
            account.currency = desired_currency
            update_fields.append("currency")

        expected_balance = calculate_investment_account_balance(user=user, currency=account.currency)
        if account.balance != expected_balance:
            account.balance = expected_balance
            update_fields.append("balance")

        if update_fields:
            account.save(update_fields=[*update_fields, "updated_at"])

        return account
