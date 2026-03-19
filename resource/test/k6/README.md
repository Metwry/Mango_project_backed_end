# k6 Load Scripts

This directory contains a k6 suite aligned with the current Django backend routes, login behavior, and snapshot query constraints.

## Files

- `p0_funds.js`: write-heavy funds path
- `p1_market.js`: market reads plus optional watchlist writes
- `p2_queries.js`: snapshot and history query path
- `p3_soak_mixed.js`: long-running mixed API soak
- `p4_auth.js`: login and token refresh path
- `lib/common.js`: shared helpers

## Prerequisites

1. Install `k6`.
2. Start the backend, PostgreSQL, Redis, and Celery as needed.
3. For mixed soak tests, make sure beat and workers are running before executing `p3_soak_mixed.js`.
4. Prepare one or more test users with valid accounts and market data.

Suggested local startup:

- PowerShell: `powershell -ExecutionPolicy Bypass -File resource/scripts/windows/start_celery.ps1 -WithBeat`
- Bash: `./resource/scripts/unix/start_celery.sh --with-beat`
- Web: `./resource/scripts/macos/start_web.sh` or `python manage.py runserver 0.0.0.0:8000`

## Required environment variables

All authenticated scripts require:

- `BASE_URL` default: `http://127.0.0.1:8000`
- `USERNAME` or `EMAIL`
- `PASSWORD`

If `EMAIL` is set, the shared login helper will send `{"email": "...", "password": "..."}`.
Otherwise it will send `{"username": "...", "password": "..."}`.

`p0_funds.js` also requires:

- `TX_ACCOUNT_ID`
- `TRANSFER_FROM_ACCOUNT_ID`
- `TRANSFER_TO_ACCOUNT_ID`
- `BUY_INSTRUMENT_ID`
- `BUY_CASH_ACCOUNT_ID`

Optional for `p0_funds.js`:

- `SELL_INSTRUMENT_ID`
- `SELL_CASH_ACCOUNT_ID`
- `HOT_TX_ID`
- `HOT_TRANSFER_ID`

Optional for market and soak scripts:

- `WATCHLIST_SYMBOL` default: `AAPL.US`
- `QUOTE_ITEMS_JSON` default: `[{"market":"US","short_code":"AAPL"}]`
- `FX_BASE` default: `USD`
- `ENABLE_WATCHLIST_WRITES`
  - `p1_market.js` default: `true`
  - `p3_soak_mixed.js` default: `false`

Optional for query scripts:

- `SNAPSHOT_LEVEL` default: `M15`
- `SNAPSHOT_START_TIME`
- `SNAPSHOT_END_TIME`
- `SNAPSHOT_LIMIT`
- `SNAPSHOT_ACCOUNT_ID`
- `SNAPSHOT_INSTRUMENT_ID`
- `HISTORY_ACCOUNT_ID`
- `HISTORY_INSTRUMENT_ID`
- `HISTORY_LIMIT` default: `100`
- `HISTORY_MAX_OFFSET` default: `300`
- `TX_ACTIVITY_TYPE` default: `manual`
- `TX_MAX_PAGE` default: `10`
- `TX_PAGE_SIZE` default: `50`

Optional for auth scripts:

- `REGISTER_EMAIL_DOMAIN`
- `REGISTER_EMAIL_PREFIX` default: `k6-register`
- `RESET_EMAIL`
- `ENABLE_EMAIL_CODE_FLOW=true`
- `ENABLE_RESET_CODE_FLOW=true`

Optional for P0 weight overrides:

- `BUY_WEIGHT` default: `30`
- `SELL_WEIGHT` default: `25`
- `MANUAL_TX_WEIGHT` default: `25`
- `TRANSFER_WEIGHT` default: `20`
- `HOT_REVERSE_WEIGHT` default: `10`

Optional for soak scripts:

- `SOAK_VUS` default: `20`
- `SOAK_DURATION` default: `30m`

## Examples

PowerShell example for P0:

```powershell
$env:BASE_URL="http://127.0.0.1:8000"
$env:USERNAME="invest_concurrency_user"
$env:PASSWORD="test123456"
$env:TX_ACCOUNT_ID="1"
$env:TRANSFER_FROM_ACCOUNT_ID="1"
$env:TRANSFER_TO_ACCOUNT_ID="2"
$env:BUY_INSTRUMENT_ID="10"
$env:BUY_CASH_ACCOUNT_ID="1"
$env:SELL_INSTRUMENT_ID="10"
$env:SELL_CASH_ACCOUNT_ID="1"
k6 run resource/test/k6/p0_funds.js
```

PowerShell example for P1:

```powershell
$env:BASE_URL="http://127.0.0.1:8000"
$env:USERNAME="market_basic_user"
$env:PASSWORD="test123456"
$env:QUOTE_ITEMS_JSON='[{"market":"US","short_code":"AAPL"},{"market":"CN","short_code":"600519"}]'
k6 run resource/test/k6/p1_market.js
```

PowerShell example for P2 query pressure:

```powershell
$env:BASE_URL="http://127.0.0.1:8000"
$env:EMAIL="snapshot_query_user@example.com"
$env:PASSWORD="test123456"
$env:SNAPSHOT_LEVEL="H4"
$env:SNAPSHOT_LIMIT="500"
$env:HISTORY_MAX_OFFSET="1000"
k6 run resource/test/k6/p2_queries.js
```

PowerShell example for P3 with a longer soak:

```powershell
$env:BASE_URL="http://127.0.0.1:8000"
$env:USERNAME="snapshot_query_user"
$env:PASSWORD="test123456"
$env:SOAK_VUS="30"
$env:SOAK_DURATION="2h"
k6 run resource/test/k6/p3_soak_mixed.js
```

PowerShell example for P4 auth path:

```powershell
$env:BASE_URL="http://127.0.0.1:8000"
$env:USERNAME="login_basic@example.com"
$env:PASSWORD="test123456"
$env:RESET_EMAIL="login_basic@example.com"
$env:ENABLE_RESET_CODE_FLOW="true"
k6 run resource/test/k6/p4_auth.js
```

## Stage overrides

The ramping scripts support simple stage overrides:

- `START_VUS`
- `STAGE_1_DURATION`, `STAGE_1_TARGET`
- `STAGE_2_DURATION`, `STAGE_2_TARGET`
- `STAGE_3_DURATION`, `STAGE_3_TARGET`
- `STAGE_4_DURATION`, `STAGE_4_TARGET`

## Notes

- `p0_funds.js` accepts some business conflict responses because concurrent sell/reverse tests can legitimately return `400` or `409`.
- `p1_market.js` accepts some `400` responses for watchlist and FX scenarios because invalid symbols, duplicate operations, or unsupported base currency are valid business outcomes.
- `p2_queries.js` defaults `M15` to the last 24 hours. If you need a longer window, switch `SNAPSHOT_LEVEL` to `H4`, `D1`, or `MON1`, or pass a narrower custom time range.
- `p3_soak_mixed.js` is designed to run while Celery beat and workers are already running.
- `p4_auth.js` covers login, token refresh, and optional send-code endpoints. It does not complete full register/reset flows because the verification code is not readable from the cache or API response.
- `p4_auth.js` can test email code endpoints only when you point it at a safe SMTP target.

