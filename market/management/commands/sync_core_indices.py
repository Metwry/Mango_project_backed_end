from __future__ import annotations

from django.core.management.base import BaseCommand
from django.db import transaction

from market.models import Instrument
from market.services.index.catalog import index_definitions_for_markets


class Command(BaseCommand):
    help = "Sync the fixed set of core market indices (US/CN/HK) into Instrument."

    UPSERT_FIELDS = (
        "short_code",
        "name",
        "asset_class",
        "market",
        "exchange",
        "base_currency",
        "is_active",
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--markets",
            nargs="*",
            choices=["cn", "hk", "us"],
            default=["cn", "hk", "us"],
            help="Markets to sync core indices for. Default: cn hk us",
        )

    def handle(self, *args, **options):
        selected = set(options.get("markets") or ["cn", "hk", "us"])
        market_map = {
            "cn": Instrument.Market.CN,
            "hk": Instrument.Market.HK,
            "us": Instrument.Market.US,
        }
        target_markets = {market_map[item] for item in selected if item in market_map}
        definitions = index_definitions_for_markets(target_markets)
        if not definitions:
            self.stdout.write(self.style.WARNING("No core indices selected."))
            return

        symbols = [item.symbol for item in definitions]
        existing_map = {
            obj.symbol: obj
            for obj in Instrument.objects.filter(symbol__in=symbols).only("id", "symbol", *self.UPSERT_FIELDS)
        }

        to_create: list[Instrument] = []
        to_update: list[Instrument] = []

        for item in definitions:
            existing = existing_map.get(item.symbol)
            if existing is None:
                to_create.append(
                    Instrument(
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
                continue

            changed = False
            incoming = {
                "short_code": item.short_code,
                "name": item.name,
                "asset_class": Instrument.AssetClass.INDEX,
                "market": item.market,
                "exchange": item.exchange,
                "base_currency": item.base_currency,
                "is_active": True,
            }
            for field_name, incoming_value in incoming.items():
                if getattr(existing, field_name) != incoming_value:
                    setattr(existing, field_name, incoming_value)
                    changed = True
            if changed:
                to_update.append(existing)

        with transaction.atomic():
            if to_create:
                Instrument.objects.bulk_create(to_create, batch_size=100)
            if to_update:
                Instrument.objects.bulk_update(to_update, fields=list(self.UPSERT_FIELDS), batch_size=100)

        self.stdout.write(
            self.style.SUCCESS(
                f"sync_core_indices done selected={sorted(target_markets)} created={len(to_create)} updated={len(to_update)}"
            )
        )
