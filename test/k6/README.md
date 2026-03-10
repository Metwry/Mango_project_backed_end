# k6 Load Scripts

This directory contains a first-pass k6 suite aligned with the current Django backend.

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
3. Prepare one or more test users with valid accounts and market data.

## Required environment variables

All authenticated scripts require:

- `BASE_URL`
- `USERNAME` or `EMAIL`
- `PASSWORD`

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

Optional for query scripts:

- `SNAPSHOT_LEVEL` default: `M15`
- `SNAPSHOT_START_TIME`
- `SNAPSHOT_END_TIME`
- `SNAPSHOT_LIMIT`
- `SNAPSHOT_ACCOUNT_ID`
- `SNAPSHOT_INSTRUMENT_ID`
- `HISTORY_ACCOUNT_ID`
- `HISTORY_INSTRUMENT_ID`
- `TX_ACTIVITY_TYPE` default: `manual`

Optional for auth scripts:

- `REGISTER_EMAIL_DOMAIN`
- `RESET_EMAIL`
- `ENABLE_EMAIL_CODE_FLOW=true`
- `ENABLE_RESET_CODE_FLOW=true`

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
k6 run test/k6/p0_funds.js
```

PowerShell example for P1:

```powershell
$env:BASE_URL="http://127.0.0.1:8000"
$env:USERNAME="market_basic_user"
$env:PASSWORD="test123456"
$env:QUOTE_ITEMS_JSON='[{"market":"US","short_code":"AAPL"},{"market":"CN","short_code":"600519"}]'
k6 run test/k6/p1_market.js
```

PowerShell example for P3 with a longer soak:

```powershell
$env:BASE_URL="http://127.0.0.1:8000"
$env:USERNAME="snapshot_query_user"
$env:PASSWORD="test123456"
$env:SOAK_VUS="30"
$env:SOAK_DURATION="2h"
k6 run test/k6/p3_soak_mixed.js
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
- `p3_soak_mixed.js` is designed to run while Celery beat and workers are already running.
- `p4_auth.js` can test email code endpoints only when you point it at a safe SMTP target.
