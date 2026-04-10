import json
from unittest.mock import patch

from django.test import SimpleTestCase

from ai.tools.general.tools import get_fx_rate


class GeneralFxToolTests(SimpleTestCase):
    @patch("ai.tools.general.tools.get_fx_rates")
    def test_get_fx_rate_returns_usd_based_pair(self, mocked_get_fx_rates):
        mocked_get_fx_rates.return_value = {
            "base": "USD",
            "updated_at": "2026-04-10T16:00:00+08:00",
            "rates": {"USD": 1.0, "CNY": 7.12, "HKD": 7.83},
        }

        payload = json.loads(get_fx_rate.invoke({"quote_currency": "cny"}))

        self.assertEqual(payload["base_currency"], "USD")
        self.assertEqual(payload["quote_currency"], "CNY")
        self.assertEqual(payload["pair"], "USD/CNY")
        self.assertEqual(payload["rate"], 7.12)
        self.assertEqual(payload["expression"], "1 USD = 7.12 CNY")
        mocked_get_fx_rates.assert_called_once_with("USD")

    @patch("ai.tools.general.tools.get_fx_rates")
    def test_get_fx_rate_rejects_unsupported_quote_currency(self, mocked_get_fx_rates):
        mocked_get_fx_rates.return_value = {
            "base": "USD",
            "updated_at": "2026-04-10T16:00:00+08:00",
            "rates": {"USD": 1.0, "CNY": 7.12},
        }

        with self.assertRaises(ValueError):
            get_fx_rate.invoke({"quote_currency": "EUR"})
