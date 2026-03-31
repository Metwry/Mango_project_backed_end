# Scripts Directory / 脚本目录

## 中文

- 定位：存放环境初始化、Conda Python 依赖安装，以及 Celery 启停脚本。
- Python 依赖安装统一基于 conda 环境，不再提供普通 `venv` 安装脚本。
- 当前路径：`resource/scripts/`
- 目录划分：
  - `resource/scripts/windows/`：PowerShell 脚本
  - `resource/scripts/unix/`：Unix shell 脚本目录
  - `resource/scripts/macos/`：macOS 专用脚本目录
- Celery 启动约定：
  - `start_celery.*` 默认使用 `Targets all`
  - `all` 现在表示启动一个统一 worker，监听全部已配置业务队列，再附加一个 `beat`
  - Windows `start_celery.ps1` 默认等价于 `-Targets all -WithBeat -Pool threads -Concurrency 4`
  - 如果只想启动 worker、不带 `beat`，显式传 `-WithBeat:$false`
  - 如果需要拆分为 4 个独立 worker，使用 `Targets market_sync,snapshot_capture,snapshot_aggregate,snapshot_cleanup`
  - Windows 默认 `threads` 表示 1 个 worker 进程下 4 个并发线程；如果你要严格 4 个子进程，更适合在 Unix/macOS 上使用 `prefork`
- 当前 RabbitMQ / Celery 运行方式：
  - `beat` 启动时会投递一次 `market_sync` 的全量初始化任务
  - 周期任务会带 `expires`
  - `market_sync`、`snapshot_capture` 队列附带 RabbitMQ `x-message-ttl`
- 当前 `resource/scripts/macos/` 仅保留：
  - `bootstrap_first_run_conda.sh`
  - `install_python_deps_conda.sh`
  - `start_celery.sh`
  - `stop_celery.sh`

## English

- Role: contains environment bootstrap, conda-based Python dependency installation, and Celery lifecycle scripts.
- Python dependency installation is conda-only; plain `venv` installers are no longer provided.
- Current path: `resource/scripts/`
- Layout:
  - `resource/scripts/windows/`: PowerShell scripts
  - `resource/scripts/unix/`: Unix shell scripts
  - `resource/scripts/macos/`: macOS-specific scripts
- Celery startup conventions:
  - `start_celery.*` uses `Targets all` by default
  - `all` now means one unified worker that listens to all configured business queues, plus one `beat`
  - Windows `start_celery.ps1` defaults to `-Targets all -WithBeat -Pool threads -Concurrency 4`
  - To start only the worker without `beat`, pass `-WithBeat:$false`
  - To keep four isolated workers, use `Targets market_sync,snapshot_capture,snapshot_aggregate,snapshot_cleanup`
  - Windows keeps `threads` by default, which means 4 concurrent threads inside one worker process; strict multi-process `prefork` is better suited to Unix/macOS
- Current RabbitMQ / Celery behavior:
  - `beat` publishes one forced `market_sync` refresh on startup
  - periodic tasks carry `expires`
  - `market_sync` and `snapshot_capture` queues use RabbitMQ `x-message-ttl`
- `resource/scripts/macos/` now keeps only:
  - `bootstrap_first_run_conda.sh`
  - `install_python_deps_conda.sh`
  - `start_celery.sh`
  - `stop_celery.sh`
