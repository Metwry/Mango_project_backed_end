from __future__ import annotations

import os
import random
import re
import time
from contextlib import redirect_stderr, redirect_stdout
from dataclasses import dataclass, replace
from datetime import datetime
from http.client import RemoteDisconnected
from io import StringIO
from typing import Callable, Iterable, Iterator, Sequence

import requests
from django.core.management.base import BaseCommand, CommandError
from django.db import transaction
from django.utils import timezone

from market.models import Instrument
from market.services.logo_service import build_logo_metadata
from market.services.data.core_indices import index_definitions_for_markets


DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/123.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json,text/plain,*/*",
}
COINGECKO_MARKETS_URL = "https://api.coingecko.com/api/v3/coins/markets"
STOOQ_QUOTE_URL = "https://stooq.com/q/l/"
DEFAULT_CRYPTO_PROXY = os.getenv("SYNC_SYMBOLS_PROXY", "").strip()
US_EXCHANGE_SUFFIXES = {"US", "N", "A", "P", "Q", "O", "OQ", "OB", "PK", "TO"}


@dataclass(frozen=True)
class ForexPair:
    pair: str
    fallback_name: str
    stooq_symbol: str


TOP20_FOREX_PAIRS: tuple[ForexPair, ...] = (
    ForexPair("EUR/USD", "Euro / US Dollar", "eurusd"),
    ForexPair("GBP/USD", "British Pound / US Dollar", "gbpusd"),
    ForexPair("USD/JPY", "US Dollar / Japanese Yen", "usdjpy"),
    ForexPair("AUD/USD", "Australian Dollar / US Dollar", "audusd"),
    ForexPair("USD/CAD", "US Dollar / Canadian Dollar", "usdcad"),
    ForexPair("USD/CHF", "US Dollar / Swiss Franc", "usdchf"),
    ForexPair("NZD/USD", "New Zealand Dollar / US Dollar", "nzdusd"),
    ForexPair("EUR/GBP", "Euro / British Pound", "eurgbp"),
    ForexPair("EUR/JPY", "Euro / Japanese Yen", "eurjpy"),
    ForexPair("GBP/JPY", "British Pound / Japanese Yen", "gbpjpy"),
    ForexPair("AUD/JPY", "Australian Dollar / Japanese Yen", "audjpy"),
    ForexPair("EUR/AUD", "Euro / Australian Dollar", "euraud"),
    ForexPair("EUR/CHF", "Euro / Swiss Franc", "eurchf"),
    ForexPair("USD/CNH", "US Dollar / Chinese Yuan Offshore", "usdcnh"),
    ForexPair("USD/HKD", "US Dollar / Hong Kong Dollar", "usdhkd"),
    ForexPair("USD/SGD", "US Dollar / Singapore Dollar", "usdsgd"),
    ForexPair("USD/ZAR", "US Dollar / South African Rand", "usdzar"),
    ForexPair("USD/MXN", "US Dollar / Mexican Peso", "usdmxn"),
    ForexPair("USD/TRY", "US Dollar / Turkish Lira", "usdtry"),
    ForexPair("XAU/USD", "Gold / US Dollar", "xauusd"),
)


@dataclass(frozen=True)
class InstrumentPayload:
    symbol: str
    short_code: str
    name: str
    asset_class: str
    market: str
    exchange: str | None
    base_currency: str | None
    logo_url: str | None = None
    logo_color: str | None = None
    logo_source: str | None = None
    logo_updated_at: datetime | None = None
    is_active: bool = True

    def as_model_kwargs(self) -> dict[str, object]:
        return {
            "symbol": self.symbol,
            "short_code": self.short_code,
            "name": self.name,
            "asset_class": self.asset_class,
            "market": self.market,
            "exchange": self.exchange,
            "base_currency": self.base_currency,
            "logo_url": self.logo_url,
            "logo_color": self.logo_color,
            "logo_source": self.logo_source,
            "logo_updated_at": self.logo_updated_at,
            "is_active": self.is_active,
        }


@dataclass
class MarketSyncProgress:
    label: str
    status: str = "pending"
    fetched: int = 0
    persisted: int = 0
    created: int = 0
    updated: int = 0
    message: str = ""


def build_session(proxy_url: str = "") -> requests.Session:
    session = requests.Session()
    session.trust_env = False
    session.headers.update(DEFAULT_HEADERS)
    if proxy_url:
        session.proxies.update({"http": proxy_url, "https": proxy_url})
    return session


def chunked(items: Sequence[str], chunk_size: int) -> Iterator[Sequence[str]]:
    for idx in range(0, len(items), chunk_size):
        yield items[idx : idx + chunk_size]


def call_with_retry(
    fn: Callable[[], object],
    *,
    name: str,
    retries: int = 4,
    base_sleep: float = 1.0,
    max_sleep: float = 8.0,
    logger: Callable[[str], None] | None = None,
) -> object:
    last_exc: Exception | None = None
    for attempt in range(1, retries + 1):
        try:
            return fn()
        except Exception as exc:  # noqa: BLE001
            last_exc = exc
            if attempt >= retries:
                break
            wait_s = min(max_sleep, base_sleep * (2 ** (attempt - 1)))
            wait_s = wait_s * random.uniform(0.8, 1.2)
            if logger:
                logger(f"[{name}] attempt {attempt}/{retries} failed: {exc}; retry in {wait_s:.1f}s")
            time.sleep(wait_s)
    if last_exc is None:
        raise RuntimeError(f"[{name}] unexpected retry failure without exception")
    raise last_exc


class Command(BaseCommand):
    help = (
        "Sync instruments for CN/HK/US stocks, top 20 FX pairs, and top 50 crypto "
        "by market cap. Markets are isolated: one failure will not block others."
    )

    UPSERT_FIELDS = (
        "short_code",
        "name",
        "asset_class",
        "market",
        "exchange",
        "base_currency",
        "logo_url",
        "logo_source",
        "logo_updated_at",
        "is_active",
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--markets",
            nargs="*",
            choices=["cn", "hk", "us", "fx", "crypto"],
            help="Only sync selected markets. Default: all markets.",
        )
        parser.add_argument(
            "--limit-per-market",
            type=int,
            default=0,
            help="Persist only first N records per market (for smoke tests).",
        )
        parser.add_argument(
            "--crypto-proxy",
            default=DEFAULT_CRYPTO_PROXY,
            help="Optional proxy URL for CoinGecko, e.g. http://127.0.0.1:7897",
        )
        parser.add_argument(
            "--insert-only",
            action="store_true",
            help="Insert new symbols only; do not update existing instruments.",
        )

    def handle(self, *args, **options):
        selected_markets = set(options.get("markets") or ["cn", "hk", "us", "fx", "crypto"])
        limit_per_market = max(0, int(options.get("limit_per_market") or 0))
        crypto_proxy = (options.get("crypto_proxy") or "").strip()
        insert_only = bool(options.get("insert_only"))
        self.smoke_mode = limit_per_market > 0

        if limit_per_market:
            self.stdout.write(
                self.style.WARNING(
                    f"Smoke mode enabled: only first {limit_per_market} record(s) "
                    "per market will be persisted."
                )
            )
        if crypto_proxy:
            self.stdout.write(f"Crypto fetch will use proxy: {crypto_proxy}")
        if insert_only:
            self.stdout.write("Insert-only mode enabled: existing instruments will not be updated.")

        market_jobs = [
            ("cn", "A-shares", self.fetch_cn_stocks, 5),
            ("hk", "HK-shares", self.fetch_hk_stocks, 6),
            ("us", "US-shares", self.fetch_us_stocks, 5),
            ("fx", "Top 20 FX pairs", self.fetch_top_forex_pairs, 4),
            ("crypto", "Top 50 Crypto", lambda: self.fetch_top_crypto(proxy_url=crypto_proxy), 5),
        ]

        progress_by_market: dict[str, MarketSyncProgress] = {
            market_key: MarketSyncProgress(label=market_label)
            for market_key, market_label, _, _ in market_jobs
            if market_key in selected_markets
        }
        results: list[tuple[str, bool, str]] = []
        self._render_market_progress(progress_by_market)

        for market_key, market_label, fetcher, retries in market_jobs:
            if market_key not in selected_markets:
                continue

            progress = progress_by_market[market_key]
            progress.status = "fetching"
            progress.message = ""
            self._render_market_progress(progress_by_market)
            self.stdout.write(f"[{market_label}] fetching...")
            try:
                fetched = call_with_retry(
                    fetcher,
                    name=market_label,
                    retries=retries,
                    base_sleep=1.0,
                    max_sleep=10.0,
                    logger=self._warn,
                )
                fetched = self.attach_index_metadata(fetched, market_key=market_key)
                records = fetched[:limit_per_market] if limit_per_market else fetched
                if not records:
                    raise ValueError(f"{market_label} returned empty records")
                progress.status = "enriching"
                progress.fetched = len(fetched)
                progress.message = ""
                self._render_market_progress(progress_by_market)
                records = self.attach_logo_metadata(records)

                progress.status = "upserting"
                progress.persisted = len(records)
                self._render_market_progress(progress_by_market)
                created, updated, persisted_total = self.upsert_instruments(records, insert_only=insert_only)
                progress.status = "done"
                progress.persisted = persisted_total
                progress.created = created
                progress.updated = updated
                self._render_market_progress(progress_by_market)
                self.stdout.write(
                    self.style.SUCCESS(
                        f"[{market_label}] success: fetched={len(fetched)}, "
                        f"persisted={persisted_total}, created={created}, updated={updated}, "
                        f"insert_only={insert_only}"
                    )
                )
                results.append((market_label, True, ""))
            except (
                requests.RequestException,
                RemoteDisconnected,
                ConnectionError,
                TimeoutError,
                ValueError,
                RuntimeError,
            ) as exc:
                progress.status = "failed"
                progress.message = str(exc)
                self._render_market_progress(progress_by_market)
                self.stdout.write(self.style.ERROR(f"[{market_label}] failed: {exc}"))
                results.append((market_label, False, str(exc)))
            except Exception as exc:  # noqa: BLE001
                progress.status = "failed"
                progress.message = str(exc)
                self._render_market_progress(progress_by_market)
                self.stdout.write(self.style.ERROR(f"[{market_label}] failed with unexpected error: {exc}"))
                results.append((market_label, False, str(exc)))

        if not results:
            raise CommandError("No market selected. Use --markets cn hk us fx crypto")

        success_count = sum(1 for _, ok, _ in results if ok)
        fail_count = len(results) - success_count
        self.stdout.write(f"Sync done: success={success_count}, failed={fail_count}")

        for market_label, ok, err_msg in results:
            if not ok:
                self.stdout.write(self.style.WARNING(f"- {market_label}: {err_msg}"))

        if success_count == 0:
            raise CommandError("All market sync jobs failed.")

    def _render_market_progress(self, progress_by_market: dict[str, MarketSyncProgress]) -> None:
        if not progress_by_market:
            return

        rows = [
            (
                item.label,
                item.status,
                str(item.fetched),
                str(item.persisted),
                str(item.created),
                str(item.updated),
                item.message,
            )
            for item in progress_by_market.values()
        ]
        headers = ("Market", "Status", "Fetched", "Persisted", "Created", "Updated", "Message")
        widths = [
            max(len(header), *(len(row[idx]) for row in rows))
            for idx, header in enumerate(headers)
        ]

        def _fmt(row: tuple[str, ...]) -> str:
            return " | ".join(cell.ljust(widths[idx]) for idx, cell in enumerate(row))

        divider = "-+-".join("-" * width for width in widths)
        self.stdout.write("")
        self.stdout.write("Market sync progress")
        self.stdout.write(_fmt(headers))
        self.stdout.write(divider)
        for row in rows:
            self.stdout.write(_fmt(row))

    def _warn(self, message: str) -> None:
        self.stdout.write(self.style.WARNING(message))

    def _import_akshare(self):
        try:
            import akshare as ak  # type: ignore
        except Exception as exc:  # noqa: BLE001
            raise RuntimeError(
                "akshare import failed. Install it in the active environment: pip install akshare"
            ) from exc
        return ak

    def fetch_cn_stocks(self) -> list[InstrumentPayload]:
        ak = self._import_akshare()
        df = ak.stock_info_a_code_name()
        if df is None or df.empty:
            raise ValueError("A-share API returned empty dataframe")
        if "code" not in df.columns or "name" not in df.columns:
            raise ValueError(f"Unexpected A-share columns: {list(df.columns)}")

        rows = df.dropna(subset=["code", "name"])
        records: list[InstrumentPayload] = []
        for _, row in rows.iterrows():
            code = self.normalize_cn_code(row["code"])
            name = str(row["name"]).strip()
            if not code or not name:
                continue
            exchange = self.guess_cn_exchange(code)
            records.append(
                InstrumentPayload(
                    symbol=f"{code}.{exchange}",
                    short_code=code,
                    name=name,
                    asset_class=Instrument.AssetClass.STOCK,
                    market=Instrument.Market.CN,
                    exchange=exchange,
                    base_currency="CNY",
                    is_active=True,
                )
            )
        return records

    def fetch_hk_stocks(self) -> list[InstrumentPayload]:
        ak = self._import_akshare()
        df = self.run_quietly(ak.stock_hk_spot)
        if df is None or df.empty:
            raise ValueError("HK-share API returned empty dataframe")

        columns = [str(col) for col in df.columns]
        code_col = self.pick_column(columns, keywords=["code", "symbol", "ticker"], fallback_index=1)
        name_col = self.pick_column(columns, keywords=["name", "cname"], fallback_index=2)
        alt_name_col = self.pick_column(columns, keywords=["ename", "english"], fallback_index=3)
        if code_col is None:
            raise ValueError(f"Unexpected HK-share columns: {list(df.columns)}")

        rows = df.dropna(subset=[code_col])
        records: list[InstrumentPayload] = []
        for _, row in rows.iterrows():
            raw_code = str(row.get(code_col, "")).strip()
            code = raw_code.zfill(5) if raw_code.isdigit() else raw_code
            cn_name = str(row.get(name_col, "")).strip() if name_col else ""
            en_name = str(row.get(alt_name_col, "")).strip() if alt_name_col else ""
            name = cn_name or en_name
            if not code or not name:
                continue
            records.append(
                InstrumentPayload(
                    symbol=f"{code}.HK",
                    short_code=code,
                    name=name,
                    asset_class=Instrument.AssetClass.STOCK,
                    market=Instrument.Market.HK,
                    exchange="HKEX",
                    base_currency="HKD",
                    is_active=True,
                )
            )
        return records

    def fetch_us_stocks(self) -> list[InstrumentPayload]:
        ak = self._import_akshare()
        if getattr(self, "smoke_mode", False):
            # Fast connectivity check for smoke mode: verify US market endpoint is reachable.
            sample_df = ak.stock_us_daily(symbol="AAPL")
            if sample_df is None or sample_df.empty:
                raise ValueError("US smoke fetch failed: stock_us_daily(AAPL) returned empty dataframe")
            return [
                InstrumentPayload(
                    symbol="AAPL.US",
                    short_code="AAPL",
                    name="Apple Inc.",
                    asset_class=Instrument.AssetClass.STOCK,
                    market=Instrument.Market.US,
                    exchange="NASDAQ",
                    base_currency="USD",
                    is_active=True,
                )
            ]

        df = self.run_quietly(ak.stock_us_spot)
        if df is None or df.empty:
            raise ValueError("US-share API returned empty dataframe")
        if "symbol" not in df.columns:
            raise ValueError(f"Unexpected US-share columns: {list(df.columns)}")

        rows = df.dropna(subset=["symbol"])
        records: list[InstrumentPayload] = []
        for _, row in rows.iterrows():
            short_code = self.normalize_us_code(row["symbol"])
            cname = str(row.get("cname", "")).strip()
            ename = str(row.get("name", "")).strip()
            name = cname or ename
            if not short_code or not name:
                continue
            exchange = str(row.get("market", "")).strip().upper() or "US"
            records.append(
                InstrumentPayload(
                    symbol=f"{short_code}.US",
                    short_code=short_code,
                    name=name,
                    asset_class=Instrument.AssetClass.STOCK,
                    market=Instrument.Market.US,
                    exchange=exchange,
                    base_currency="USD",
                    is_active=True,
                )
            )
        return records

    def fetch_top_forex_pairs(self) -> list[InstrumentPayload]:
        session = build_session()
        live_count = 0
        missing_pairs: list[str] = []
        records: list[InstrumentPayload] = []

        for pair in TOP20_FOREX_PAIRS:
            try:
                quote = self.fetch_stooq_fx_quote(session=session, stooq_symbol=pair.stooq_symbol)
            except Exception as exc:  # noqa: BLE001
                self._warn(f"[Top 20 FX pairs] quote fetch failed for {pair.pair}: {exc}")
                quote = {"name": "", "is_live": False}
            if quote["is_live"]:
                live_count += 1
            else:
                missing_pairs.append(pair.pair)

            display_name = quote["name"] or pair.fallback_name
            quote_currency = pair.pair.split("/")[-1]
            records.append(
                InstrumentPayload(
                    symbol=f"{pair.pair}.FX",
                    short_code=pair.pair,
                    name=display_name,
                    asset_class=Instrument.AssetClass.FOREX,
                    market=Instrument.Market.FX,
                    exchange="Stooq",
                    base_currency=quote_currency,
                    is_active=True,
                )
            )

        if live_count == 0:
            raise ValueError("Stooq FX API returned no live quotes")
        if missing_pairs:
            self._warn(
                "[Top 20 FX pairs] no live quote for "
                f"{len(missing_pairs)} pair(s), fallback names used: {', '.join(missing_pairs)}"
            )
        return records

    def fetch_top_crypto(self, *, proxy_url: str = "") -> list[InstrumentPayload]:
        session = build_session(proxy_url=proxy_url)
        params = {
            "vs_currency": "usd",
            "order": "market_cap_desc",
            "per_page": 250,
            "page": 1,
            "sparkline": "false",
        }
        resp = session.get(COINGECKO_MARKETS_URL, params=params, timeout=25)
        resp.raise_for_status()
        data = resp.json()
        if not isinstance(data, list) or not data:
            raise ValueError("CoinGecko returned empty payload")

        records: list[InstrumentPayload] = []
        seen_symbols: set[str] = set()
        for coin in data:
            short_code = str(coin.get("symbol", "")).upper().strip()
            name = str(coin.get("name", "")).strip()
            if not short_code or not name:
                continue
            symbol = f"{short_code}.CRYPTO"
            if symbol in seen_symbols:
                continue
            seen_symbols.add(symbol)
            records.append(
                InstrumentPayload(
                    symbol=symbol,
                    short_code=short_code,
                    name=name,
                    asset_class=Instrument.AssetClass.CRYPTO,
                    market=Instrument.Market.CRYPTO,
                    exchange="CoinGecko",
                    base_currency="USD",
                    is_active=True,
                )
            )
            if len(records) >= 50:
                break

        if len(records) < 50:
            raise ValueError(f"CoinGecko unique symbols < 50, got {len(records)}")
        return records

    def attach_logo_metadata(self, records: list[InstrumentPayload]) -> list[InstrumentPayload]:
        now = timezone.now()
        enriched: list[InstrumentPayload] = []
        for item in records:
            if item.asset_class == Instrument.AssetClass.INDEX:
                enriched.append(
                    replace(
                        item,
                        logo_url=None,
                        logo_source=None,
                        logo_updated_at=None,
                    )
                )
                continue
            logo_url, logo_source = build_logo_metadata(short_code=item.short_code, market=item.market)
            enriched.append(
                replace(
                    item,
                    logo_url=logo_url,
                    logo_source=logo_source,
                    logo_updated_at=now if logo_url else None,
                )
            )
        return enriched

    def attach_index_metadata(self, records: list[InstrumentPayload], *, market_key: str) -> list[InstrumentPayload]:
        market_code_map = {
            "cn": Instrument.Market.CN,
            "hk": Instrument.Market.HK,
            "us": Instrument.Market.US,
        }
        market_code = market_code_map.get(str(market_key or "").strip().lower())
        if not market_code:
            return records

        enriched = list(records)
        existing_symbols = {item.symbol for item in enriched}
        for item in index_definitions_for_markets({market_code}):
            if item.symbol in existing_symbols:
                continue
            enriched.append(
                InstrumentPayload(
                    symbol=item.symbol,
                    short_code=item.short_code,
                    name=item.name,
                    asset_class=Instrument.AssetClass.INDEX,
                    market=item.market,
                    exchange=item.exchange,
                    base_currency=item.base_currency,
                    is_active=True,
                )
            )
        return enriched

    def fetch_stooq_fx_quote(self, *, session: requests.Session, stooq_symbol: str) -> dict[str, object]:
        params = {
            "s": stooq_symbol,
            "f": "sd2t2ohlcvn",
            "e": "csv",
        }

        def _request_once() -> dict[str, object]:
            resp = session.get(STOOQ_QUOTE_URL, params=params, timeout=15)
            resp.raise_for_status()
            line = resp.text.strip().splitlines()[0] if resp.text.strip() else ""
            if not line:
                raise ValueError(f"Empty Stooq response for symbol={stooq_symbol}")
            parts = [part.strip() for part in line.split(",")]
            if len(parts) < 9:
                raise ValueError(f"Unexpected Stooq response format for symbol={stooq_symbol}: {line}")
            quote_name = parts[8]
            quote_date = parts[1]
            return {
                "name": quote_name if quote_name and quote_name != stooq_symbol.upper() else "",
                "is_live": quote_date != "N/D",
            }

        return call_with_retry(
            _request_once,
            name=f"FX {stooq_symbol}",
            retries=3,
            base_sleep=0.6,
            max_sleep=4.0,
            logger=self._warn,
        )

    def upsert_instruments(
        self,
        records: Iterable[InstrumentPayload],
        *,
        insert_only: bool = False,
    ) -> tuple[int, int, int]:
        dedup_by_symbol: dict[str, InstrumentPayload] = {}
        for raw in records:
            symbol = raw.symbol.strip()[:50]
            short_code = raw.short_code.strip()[:20]
            name = raw.name.strip()[:100]
            if not symbol or not short_code or not name:
                continue
            dedup_by_symbol[symbol] = InstrumentPayload(
                symbol=symbol,
                short_code=short_code,
                name=name,
                asset_class=raw.asset_class,
                market=raw.market,
                exchange=raw.exchange,
                base_currency=raw.base_currency,
                logo_url=raw.logo_url,
                logo_color=raw.logo_color,
                logo_source=raw.logo_source,
                logo_updated_at=raw.logo_updated_at,
                is_active=raw.is_active,
            )

        if not dedup_by_symbol:
            return 0, 0, 0

        symbols = list(dedup_by_symbol.keys())
        existing_map: dict[str, Instrument] = {}
        for symbol_chunk in chunked(symbols, 2000):
            queryset = Instrument.objects.filter(symbol__in=symbol_chunk).only("id", "symbol", *self.UPSERT_FIELDS)
            for obj in queryset:
                existing_map[obj.symbol] = obj

        to_create: list[Instrument] = []
        to_update: list[Instrument] = []

        for symbol, payload in dedup_by_symbol.items():
            existing = existing_map.get(symbol)
            if existing is None:
                to_create.append(Instrument(**payload.as_model_kwargs()))
                continue
            if insert_only:
                continue

            changed = False
            for field_name in self.UPSERT_FIELDS:
                incoming_value = getattr(payload, field_name)
                if getattr(existing, field_name) != incoming_value:
                    setattr(existing, field_name, incoming_value)
                    changed = True
            if changed:
                to_update.append(existing)

        with transaction.atomic():
            if to_create:
                Instrument.objects.bulk_create(
                    to_create,
                    ignore_conflicts=True,
                    batch_size=1000,
                )
            if to_update:
                Instrument.objects.bulk_update(
                    to_update,
                    fields=list(self.UPSERT_FIELDS),
                    batch_size=1000,
                )

        return len(to_create), len(to_update), len(to_create) + len(to_update)

    @staticmethod
    def run_quietly(fn: Callable[[], object]) -> object:
        sink = StringIO()
        with redirect_stdout(sink), redirect_stderr(sink):
            return fn()

    @staticmethod
    def pick_column(
        columns: Sequence[str],
        *,
        keywords: Sequence[str],
        fallback_index: int | None = None,
    ) -> str | None:
        normalized = {col: re.sub(r"[^a-z0-9]", "", col.lower()) for col in columns}
        for keyword in keywords:
            needle = re.sub(r"[^a-z0-9]", "", keyword.lower())
            if not needle:
                continue
            for col, norm in normalized.items():
                if needle in norm:
                    return col

        if fallback_index is not None and 0 <= fallback_index < len(columns):
            return columns[fallback_index]
        return None

    @staticmethod
    def normalize_cn_code(raw_code: object) -> str:
        code = str(raw_code).strip()
        digits = re.sub(r"\D", "", code)
        if digits:
            return digits.zfill(6) if len(digits) <= 6 else digits
        return re.sub(r"[^A-Za-z0-9]", "", code).upper()

    @staticmethod
    def guess_cn_exchange(code: str) -> str:
        if code.startswith(("6", "9")):
            return "SH"
        if code.startswith(("0", "3")):
            return "SZ"
        if code.startswith(("4", "8")):
            return "BJ"
        return "CN"

    @staticmethod
    def normalize_us_code(raw_code: object) -> str:
        code = str(raw_code).strip().upper()
        if not code:
            return ""

        parts = code.split(".")
        if len(parts) > 1 and parts[0].isdigit():
            code = ".".join(parts[1:])

        parts = code.split(".")
        if len(parts) > 1 and parts[-1] in US_EXCHANGE_SUFFIXES:
            code = ".".join(parts[:-1])

        code = code.replace(".", "-").replace("/", "-")
        code = re.sub(r"[^A-Z0-9\-]", "", code)
        return code
