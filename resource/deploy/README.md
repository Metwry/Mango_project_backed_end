# Deploy Directory / 部署目录

## 中文

- 定位：存放部署层模板和系统服务描述文件。
- 当前内容：`launchd/` 下提供 Redis、PostgreSQL、Web、Celery Worker、Celery Beat 的 macOS `plist` 示例。
- 补充内容：`docker-compose.infrastructure.yml` 提供 PostgreSQL、Redis、RabbitMQ 的 Docker 基础设施编排；`docker.infrastructure.env.example` 提供对应变量模板。
- 适用场景：本地 macOS 常驻部署、重启恢复、自启动管理。
- 另一个适用场景：后端继续走 Conda 启动，但数据库、缓存、Broker 改由 Docker 托管。
- 关联说明：安装和重载方式见 [`../../MAINTENANCE.md`](../../docs/MAINTENANCE.md) 与 [`../scripts/README.md`](../scripts/README.md)。

## English

- Role: contains deployment descriptors and service templates.
- Current content: macOS `launchd` plist examples for Redis, PostgreSQL, web, Celery worker, and Celery beat.
- Extra: `docker-compose.infrastructure.yml` provides Docker infrastructure orchestration for PostgreSQL, Redis, and RabbitMQ, while `docker.infrastructure.env.example` provides a matching variable template.
- Use case: persistent local macOS deployment, reboot recovery, and service management.
- Additional use case: keep Django and Celery on the host via Conda while moving the database, cache, and broker into Docker.
- Related docs: see [`../../MAINTENANCE.md`](../../docs/MAINTENANCE.md) and [`../scripts/README.md`](../scripts/README.md).

