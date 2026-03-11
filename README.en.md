# Mango Backend Project Guide

Version: `V1.0.0`

## 1. Overview

Mango Backend is the API service behind Mango Finance. It is built with Django and Django REST Framework and owns authentication, cash-account bookkeeping, market data access, investment trade recording, portfolio snapshots, and scheduled jobs.

## 2. Stack

- Django 6
- Django REST Framework
- Simple JWT
- PostgreSQL
- Redis
- Celery
- yfinance / akshare / pandas-market-calendars

## 3. Core Domains

- [login/README.md](login/README.md): email registration, email codes, password reset, login, username update
- [accounts/README.md](accounts/README.md): accounts, transactions, transfers, reversals, archiving
- [market/README.md](market/README.md): instruments, quotes, watchlists, FX rates, market indices
- [investment/README.md](investment/README.md): buy/sell execution, positions, realized PnL
- [snapshot/README.md](snapshot/README.md): account and position snapshot capture, aggregation, query
- [shared/README.md](shared/README.md): shared constraints, exceptions, time utilities, helper functions

## 4. Repository Layout

```text
.
|-- mango_project/   Project settings, URL routing, Celery bootstrap
|-- login/           Authentication APIs
|-- accounts/        Accounts, transactions, transfers
|-- market/          Market data and instruments
|-- investment/      Trading records and positions
|-- snapshot/        Snapshot capture and query
|-- shared/          Shared infrastructure
|-- data/            Static market calendar data
|-- scripts/         Bootstrap and run scripts
|-- deploy/          Deployment descriptors
```

## 5. Runtime Requirements

- Python 3.12
- PostgreSQL
- Redis for cache and Celery broker
- SMTP provider for verification emails

See [`.env.example`](.env.example) for the environment template.

## 6. Local Startup

```bash
conda env create -f environment.yml
conda activate Back_end_project
pip install -r requirements.txt
python manage.py migrate
python manage.py runserver
```

Start background workers separately:

```bash
celery -A mango_project worker -l info
celery -A mango_project beat -l info
```

Cross-platform helper scripts are described in [scripts/README.md](scripts/README.md).

## 7. Scheduled Jobs

- Watchlist quote refresh: `accounts.tasks.task_pull_watchlist_quotes`
- 15-minute capture: `snapshot.tasks.task_capture_m15_snapshots`
- H4 / D1 / MON1 aggregation: `snapshot.tasks.task_aggregate_*`
- Snapshot cleanup: `snapshot.tasks.task_cleanup_snapshot_history`

## 8. API Entry Points

- `/api/login/`
- `/api/register/email/code/`
- `/api/register/email/`
- `/api/password/reset/code/`
- `/api/password/reset/`
- `/api/user/accounts/`
- `/api/user/transactions/`
- `/api/user/transfers/`
- `/api/user/markets/`
- `/api/investment/*`
- `/api/snapshot/*`

## 9. Testing and Operations

- Test command: `python manage.py test`
- Maintenance guide: [MAINTENANCE.md](MAINTENANCE.md)

## 10. Chinese Guide

Chinese documentation is available at [README.zh-CN.md](README.zh-CN.md).
