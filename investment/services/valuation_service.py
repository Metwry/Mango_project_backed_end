from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from accounts.services.currency_service import load_cached_usd_rates
from market.services.snapshot.quote_store import build_quote_index, get_snapshot_payload
from common.constants.market import market_currency
from common.utils.code_utils import normalize_code, strip_market_suffix
from common.utils.decimal_utils import quantize_decimal, to_decimal

from ..models import Position

POSITION_PRECISION = Decimal("0.000001")
ACCOUNT_PRECISION = Decimal("0.01")
ZERO = Decimal("0")


# 按持仓快照精度量化持仓金额相关数值。
def _q_position(value: Decimal) -> Decimal:
    return quantize_decimal(value, POSITION_PRECISION)


# 按账户展示精度量化账户金额。
def _q_account(value: Decimal) -> Decimal:
    return quantize_decimal(value, ACCOUNT_PRECISION)


# 推断持仓标的的计价币种。
def _position_currency(position: Position) -> str:
    instrument = position.instrument
    base_currency = normalize_code(getattr(instrument, "base_currency", ""))
    if base_currency:
        return base_currency
    return market_currency(instrument.market, "USD")


# 从行情索引中提取指定持仓的最新价格。
def _position_quote_price(position: Position, quote_index: dict[tuple[str, str], dict]) -> Decimal | None:
    instrument = position.instrument
    market = normalize_code(instrument.market)
    short_code = normalize_code(instrument.short_code) or strip_market_suffix(instrument.symbol)
    if not market or not short_code:
        return None
    row = quote_index.get((market, short_code))
    if not isinstance(row, dict):
        return None
    price = to_decimal(row.get("price"))
    if price is None or price <= 0:
        return None
    return price


# 计算持仓在本币下的市值，并标记是否使用了实时行情。
def _position_value_native(position: Position, quote_index: dict[tuple[str, str], dict]) -> tuple[Decimal, bool]:
    quantity = Decimal(str(position.quantity or ZERO))
    if quantity <= 0:
        return ZERO, False

    quote_price = _position_quote_price(position, quote_index)
    if quote_price is not None:
        return _q_position(quantity * quote_price), True

    cost_total = Decimal(str(position.cost_total or ZERO))
    if cost_total > 0:
        return _q_position(cost_total), False

    avg_cost = Decimal(str(position.avg_cost or ZERO))
    return _q_position(quantity * avg_cost), False


# 将本币金额按美元汇率转换为美元金额。
def _to_usd_or_raise(amount: Decimal, currency: str, usd_rates: dict[str, Decimal]) -> Decimal:
    ccy = normalize_code(currency) or "USD"
    if ccy == "USD":
        return _q_position(amount)

    rate = usd_rates.get(ccy)
    if rate is None or rate <= 0:
        raise ValueError(f"缺少汇率对数据：{ccy}/USD，请先刷新汇率后重试。")
    return _q_position(amount / rate)


# 将美元金额按目标币种汇率转换为账户本币金额。
def _from_usd_or_raise(amount_usd: Decimal, currency: str, usd_rates: dict[str, Decimal]) -> Decimal:
    ccy = normalize_code(currency) or "USD"
    if ccy == "USD":
        return _q_account(amount_usd)

    rate = usd_rates.get(ccy)
    if rate is None or rate <= 0:
        raise ValueError(f"缺少汇率对数据：USD/{ccy}，请先刷新汇率后重试。")
    return _q_account(amount_usd * rate)


@dataclass(frozen=True)
class InvestmentAccountValuation:
    account_currency: str
    balance_native: Decimal
    balance_usd: Decimal
    quoted_position_count: int
    cost_fallback_position_count: int

# 计算一组持仓对应的系统投资账户估值结果。
def calculate_investment_account_valuation(*, positions: list[Position], target_currency: str) -> InvestmentAccountValuation:
    account_currency = normalize_code(target_currency) or "USD"
    usd_rates = load_cached_usd_rates()
    quote_index = build_quote_index(get_snapshot_payload())

    total_usd = ZERO
    quoted_count = 0
    cost_fallback_count = 0

    for position in positions:
        native_value, used_quote = _position_value_native(position, quote_index)
        if used_quote:
            quoted_count += 1
        else:
            cost_fallback_count += 1
        total_usd = _q_position(total_usd + _to_usd_or_raise(native_value, _position_currency(position), usd_rates))

    return InvestmentAccountValuation(
        account_currency=account_currency,
        balance_native=_from_usd_or_raise(total_usd, account_currency, usd_rates),
        balance_usd=_q_position(total_usd),
        quoted_position_count=quoted_count,
        cost_fallback_position_count=cost_fallback_count,
    )

