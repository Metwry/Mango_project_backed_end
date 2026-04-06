from decimal import Decimal
from unittest.mock import patch

from django.test import SimpleTestCase

from market.services.pricing.conversion import convert_currency


class CurrencyConversionTests(SimpleTestCase):

    @patch("market.services.pricing.conversion.get_usd_base_fx_snapshot")
    def test_convert_usd_to_cny(self, mocked_get_fx_rate):
        mocked_get_fx_rate.return_value = {
            "base": "USD",
            "updated_at": "2026-04-06T00:00:00+08:00",
            "rates": {"USD": "1", "CNY": "7.00", "HKD": "7.80", "JPY": "150.00"},
        }

        result = convert_currency(
            amounts=[{"key": "btc_mv", "amount": "100", "currency": "USD"}],
            base_currency="CNY",
        )

        self.assertEqual(
            result,
            {
                "base_currency": "CNY",
                "items": [{"key": "btc_mv", "converted_amount": "700.00"}],
            },
        )

    @patch("market.services.pricing.conversion.get_usd_base_fx_snapshot")
    def test_convert_hkd_to_cny(self, mocked_get_fx_rate):
        mocked_get_fx_rate.return_value = {
            "base": "USD",
            "updated_at": "2026-04-06T00:00:00+08:00",
            "rates": {"USD": "1", "CNY": "7.00", "HKD": "7.80", "JPY": "150.00"},
        }

        result = convert_currency(
            amounts=[{"key": "bnb_mv", "amount": "780", "currency": "HKD"}],
            base_currency="CNY",
        )

        self.assertEqual(result["items"][0]["converted_amount"], "700.00")

    @patch("market.services.pricing.conversion.get_usd_base_fx_snapshot")
    def test_convert_cny_to_usd(self, mocked_get_fx_rate):
        mocked_get_fx_rate.return_value = {
            "base": "USD",
            "updated_at": "2026-04-06T00:00:00+08:00",
            "rates": {"USD": "1", "CNY": "7.00", "HKD": "7.80", "JPY": "150.00"},
        }

        result = convert_currency(
            amounts=[{"key": "cash", "amount": "700", "currency": "CNY"}],
            base_currency="USD",
        )

        self.assertEqual(result["items"][0]["converted_amount"], "100.00")

    @patch("market.services.pricing.conversion.get_usd_base_fx_snapshot")
    def test_convert_jpy_to_hkd(self, mocked_get_fx_rate):
        mocked_get_fx_rate.return_value = {
            "base": "USD",
            "updated_at": "2026-04-06T00:00:00+08:00",
            "rates": {"USD": "1", "CNY": "7.00", "HKD": "7.80", "JPY": "156.00"},
        }

        result = convert_currency(
            amounts=[{"key": "fx_case", "amount": "1560", "currency": "JPY"}],
            base_currency="HKD",
        )

        self.assertEqual(result["items"][0]["converted_amount"], "78.00")

    @patch("market.services.pricing.conversion.get_usd_base_fx_snapshot")
    def test_batch_conversion_preserves_keys(self, mocked_get_fx_rate):
        mocked_get_fx_rate.return_value = {
            "base": "USD",
            "updated_at": "2026-04-06T00:00:00+08:00",
            "rates": {"USD": "1", "CNY": "7.00", "HKD": "7.00", "JPY": "140.00"},
        }

        result = convert_currency(
            amounts=[
                {"key": "btc_mv", "amount": "100", "currency": "USD"},
                {"key": "cash_hkd", "amount": "70", "currency": "HKD"},
            ],
            base_currency="CNY",
        )

        self.assertEqual(
            result,
            {
                "base_currency": "CNY",
                "items": [
                    {"key": "btc_mv", "converted_amount": "700.00"},
                    {"key": "cash_hkd", "converted_amount": "70.00"},
                ],
            },
        )

    @patch("market.services.pricing.conversion.get_usd_base_fx_snapshot")
    def test_rejects_extra_metadata(self, mocked_get_fx_rate):
        mocked_get_fx_rate.return_value = {
            "base": "USD",
            "updated_at": "2026-04-06T00:00:00+08:00",
            "rates": {"USD": "1", "CNY": "7.00"},
        }

        with self.assertRaises(ValueError):
            convert_currency(
                amounts=[{"key": "btc_mv", "amount": "1", "currency": "USD", "meta": "x"}],
                base_currency="CNY",
            )
