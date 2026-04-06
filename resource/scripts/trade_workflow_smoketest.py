from __future__ import annotations

import os
import sys
from decimal import Decimal
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parents[2]
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mango_project.settings")

import django

django.setup()

from django.contrib.auth import get_user_model
from django.core.cache import cache

from accounts.models import Accounts
from ai.agent.trading_agent import TradingWorkflow
from market.models import Instrument


def main():
    User = get_user_model()
    user, _ = User.objects.get_or_create(
        username="codex_trade_test",
        defaults={"email": "codex_trade_test@example.com"},
    )
    user.set_password("test123456")
    user.save()

    usd_account, _ = Accounts.objects.get_or_create(
        user=user,
        name="美元账户",
        type=Accounts.AccountType.CASH,
        currency="USD",
        defaults={
            "balance": Decimal("10000.00"),
            "status": Accounts.Status.ACTIVE,
        },
    )
    usd_account.balance = Decimal("10000.00")
    usd_account.status = Accounts.Status.ACTIVE
    usd_account.save(update_fields=["balance", "status", "updated_at"])

    instrument, _ = Instrument.objects.get_or_create(
        symbol="AAPL.US",
        defaults={
            "short_code": "AAPL",
            "name": "Apple Inc.",
            "market": Instrument.Market.US,
            "asset_class": Instrument.AssetClass.STOCK,
            "is_active": True,
        },
    )

    cache.set(
        "markets:instrument:instrument_all",
        {
            "data": {
                "US": [
                    {
                        "short_code": "AAPL",
                        "symbol": "AAPL.US",
                        "name": "Apple Inc.",
                        "price": 185.2,
                    }
                ]
            }
        },
        timeout=None,
    )

    workflow = TradingWorkflow()
    queries = [
        "买10股苹果",
        "用美元账户买10股苹果",
        "确认",
        "取消",
    ]

    print(f"USER={user.id} ACCOUNT={usd_account.id} INSTRUMENT={instrument.id}")
    for query in queries:
        try:
            answer = workflow.execute(
                user_id=user.id,
                session_id=999001,
                query=query,
            )
        except Exception as exc:
            answer = f"ERROR: {exc!r}"
        print(f"Q: {query}")
        print(f"A: {answer}")
        print("---")


if __name__ == "__main__":
    main()
