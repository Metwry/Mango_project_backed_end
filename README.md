# Mango Backend

Version: `V1.0.0`

- [简体中文文档](README.zh-CN.md)
- [English Documentation](README.en.md)

Mango Backend is a Django REST API service for Mango Finance. It covers authentication, account bookkeeping, market data, investment trading, and periodic snapshots.

Mango Backend 是 Mango Finance 的 Django REST API 后端，覆盖认证登录、账户记账、市场行情、投资交易和周期快照。

## Modules

| Path | Responsibility |
| --- | --- |
| [login/README.md](login/README.md) | Authentication, email verification, JWT issuing |
| [accounts/README.md](accounts/README.md) | Accounts, transactions, transfers |
| [market/README.md](market/README.md) | Instrument master data, quotes, FX, watchlist |
| [investment/README.md](investment/README.md) | Buy/sell execution, positions, trade history |
| [snapshot/README.md](snapshot/README.md) | Timed snapshots, aggregation, query APIs |
| [shared/README.md](shared/README.md) | Shared exceptions, constraints, utilities |
| [mango_project/README.md](mango_project/README.md) | Django project wiring, settings, Celery bootstrap |
| [data/README.md](data/README.md) | Static market calendar data |
| [scripts/README.md](scripts/README.md) | Local bootstrap and start/stop scripts |
| [deploy/README.md](deploy/README.md) | Deployment descriptors for launchd |

## Runtime

- Python 3.12
- PostgreSQL
- Redis
- SMTP provider for email verification
- Celery worker and Celery beat

## Quick Start

1. Create the environment from `environment.yml`.
2. Copy `.env.example` to `.env` and fill secrets.
3. Run `python manage.py migrate`.
4. Start Django and Celery processes.
5. Run `python manage.py test`.

For deployment and maintenance details, see [MAINTENANCE.md](MAINTENANCE.md).
