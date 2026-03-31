# Project Wiring / 工程装配

## 中文

- 定位：`mango_project/` 是 Django 工程入口，负责配置装配而不是业务实现。
- 关键文件：`settings.py` 管理环境变量、数据库、Redis、RabbitMQ、JWT、Celery Beat 调度与队列过期策略；`urls.py` 汇总各 app 路由；`celery.py` 负责 Celery 初始化，并在 `beat` 启动时投递一次全量行情初始化任务。
- 设计思路：将业务拆分到独立 app，将定时任务策略集中在配置层，避免业务逻辑散落在工程入口文件。

## English

- Role: `mango_project/` is the Django project package and owns system wiring rather than business logic.
- Key files: `settings.py` defines environment loading, database, Redis, RabbitMQ, JWT, Celery Beat schedules, and queue expiry policies; `urls.py` composes app routes; `celery.py` initializes Celery and publishes one forced market bootstrap refresh when `beat` starts.
- Design: keep business logic inside apps and centralize operational scheduling in the project configuration layer.
