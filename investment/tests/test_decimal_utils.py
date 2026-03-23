from decimal import Decimal

from django.contrib.auth import get_user_model
from django.core.cache import cache
from django.test import SimpleTestCase, override_settings
from rest_framework import status
from rest_framework.test import APITestCase

from accounts.models import Accounts
from common.normalize import normalize_decimal
from common.utils import format_decimal_str
from investment.models import InvestmentRecord
from market.models import Instrument
from market.services.pricing.cache import USD_EXCHANGE_RATES_KEY, WATCHLIST_QUOTES_KEY


def _seed_usd_rates():
    cache.set(
        USD_EXCHANGE_RATES_KEY,
        {
            "base": "USD",
            "updated_at": "2026-03-02T00:00:00+08:00",
            "rates": {
                "USD": 1.0,
                "CNY": 7.0,
            },
        },
        timeout=None,
    )


def _seed_quotes():
    cache.set(
        WATCHLIST_QUOTES_KEY,
        {
            "updated_at": "2026-03-02T00:00:00+08:00",
            "data": {},
        },
        timeout=None,
    )


class DecimalUtilsTests(SimpleTestCase):
    def test_format_decimal_str_trims_trailing_zeros_and_negative_zero(self):
        self.assertEqual(format_decimal_str(Decimal("1.230000")), "1.23")
        self.assertEqual(format_decimal_str(Decimal("1.000000")), "1")
        self.assertEqual(format_decimal_str(Decimal("-0.000000")), "0")

    def test_normalize_decimal_converts_negative_zero_only(self):
        normalized = normalize_decimal(Decimal("-0.000000"))
        self.assertEqual(normalized, Decimal("0"))
        self.assertFalse(normalized.is_signed())
        self.assertEqual(normalize_decimal(Decimal("1.230000")), Decimal("1.230000"))


@override_settings(
    CACHES={
        "default": {
            "BACKEND": "django.core.cache.backends.locmem.LocMemCache",
            "LOCATION": "investment-decimal-utils-tests",
        }
    },
    INVESTMENT_QUOTE_WARMUP_ENABLED=False,
)
class InvestmentDecimalNormalizationTests(APITestCase):
    buy_endpoint = "/api/investment/buy/"
    sell_endpoint = "/api/investment/sell/"

    def setUp(self):
        cache.clear()
        _seed_usd_rates()
        _seed_quotes()

        user_model = get_user_model()
        self.user = user_model.objects.create_user(username="invest_decimal_user", password="test123456")
        self.client.force_authenticate(self.user)

        self.instrument = Instrument.objects.create(
            symbol="NEGZERO.US",
            short_code="NEGZERO",
            name="Negative Zero Inc.",
            market=Instrument.Market.US,
            asset_class=Instrument.AssetClass.STOCK,
            base_currency="USD",
            is_active=True,
        )
        self.cash_account = Accounts.objects.create(
            user=self.user,
            name="Decimal USD",
            type=Accounts.AccountType.BROKER,
            currency="USD",
            balance=Decimal("10000.00"),
            status=Accounts.Status.ACTIVE,
        )

    def test_sell_realized_pnl_storage_does_not_keep_negative_zero(self):
        trade_payload = {
            "instrument_id": self.instrument.id,
            "quantity": "0.278788",
            "price": "0.237248",
            "cash_account_id": self.cash_account.id,
        }

        buy_resp = self.client.post(self.buy_endpoint, trade_payload, format="json")
        self.assertEqual(buy_resp.status_code, status.HTTP_201_CREATED)

        sell_resp = self.client.post(self.sell_endpoint, trade_payload, format="json")
        self.assertEqual(sell_resp.status_code, status.HTTP_201_CREATED)
        self.assertEqual(sell_resp.data["realized_pnl"], "0")

        sell_record = InvestmentRecord.objects.get(side=InvestmentRecord.Side.SELL)
        self.assertEqual(sell_record.realized_pnl, Decimal("0"))
        self.assertFalse(sell_record.realized_pnl.is_signed())
