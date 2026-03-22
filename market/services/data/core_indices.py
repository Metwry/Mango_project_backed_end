from __future__ import annotations

from dataclasses import dataclass

from market.models import Instrument


@dataclass(frozen=True)
class IndexDefinition:
    symbol: str
    short_code: str
    name: str
    market: str
    exchange: str
    base_currency: str
    provider_symbol: str


CORE_INDEX_DEFINITIONS: tuple[IndexDefinition, ...] = (
    IndexDefinition(
        symbol="SPX.US",
        short_code="SPX",
        name="S&P500",
        market=Instrument.Market.US,
        exchange="INDEX",
        base_currency="USD",
        provider_symbol="^GSPC",
    ),
    IndexDefinition(
        symbol="NDX.US",
        short_code="NDX",
        name="纳指100",
        market=Instrument.Market.US,
        exchange="INDEX",
        base_currency="USD",
        provider_symbol="^NDX",
    ),
    IndexDefinition(
        symbol="DJI.US",
        short_code="DJI",
        name="道琼斯",
        market=Instrument.Market.US,
        exchange="INDEX",
        base_currency="USD",
        provider_symbol="^DJI",
    ),
    IndexDefinition(
        symbol="000001.SH",
        short_code="000001.SH",
        name="上证指数",
        market=Instrument.Market.CN,
        exchange="SH",
        base_currency="CNY",
        provider_symbol="000001.SS",
    ),
    IndexDefinition(
        symbol="399001.SZ",
        short_code="399001.SZ",
        name="深圳成指",
        market=Instrument.Market.CN,
        exchange="SZ",
        base_currency="CNY",
        provider_symbol="399001.SZ",
    ),
    IndexDefinition(
        symbol="HSI.HK",
        short_code="HSI",
        name="恒生指数",
        market=Instrument.Market.HK,
        exchange="HKEX",
        base_currency="HKD",
        provider_symbol="^HSI",
    ),
)


def index_definitions_for_markets(markets: set[str] | list[str] | tuple[str, ...]) -> list[IndexDefinition]:
    allow = {str(market or "").strip().upper() for market in markets if str(market or "").strip()}
    return [item for item in CORE_INDEX_DEFINITIONS if item.market in allow]


def index_definition_by_symbol(symbol: str) -> IndexDefinition | None:
    target = str(symbol or "").strip().upper()
    for item in CORE_INDEX_DEFINITIONS:
        if item.symbol == target:
            return item
    return None
