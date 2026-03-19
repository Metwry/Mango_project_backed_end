# Deploy Directory / 部署目录

## 中文

- 定位：存放部署层模板和系统服务描述文件。
- 当前内容：`launchd/` 下提供 Redis、PostgreSQL、Web、Celery Worker、Celery Beat 的 macOS `plist` 模板。
- 适用场景：本地 macOS 常驻部署、重启恢复、自启动管理。
- 关联说明：安装和重载方式见 [`../../MAINTENANCE.md`](../../docs/MAINTENANCE.md) 与 [`../scripts/README.md`](../scripts/README.md)。

## English

- Role: contains deployment descriptors and service templates.
- Current content: macOS `launchd` plist files for Redis, PostgreSQL, web, Celery worker, and Celery beat.
- Use case: persistent local macOS deployment, reboot recovery, and service management.
- Related docs: see [`../../MAINTENANCE.md`](../../docs/MAINTENANCE.md) and [`../scripts/README.md`](../scripts/README.md).

