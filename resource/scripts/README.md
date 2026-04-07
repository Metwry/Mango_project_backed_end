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
  - `start_celery.*` 默认使用 `Targets market,snapshot,ai`
  - `all` 现在表示同时启动 3 个业务 worker：`market`、`snapshot`、`ai`
  - Windows `start_celery.ps1` 默认等价于 `-Targets market,snapshot,ai -WithBeat -Pool threads -Concurrency 4`
  - 如果只想启动 worker、不带 `beat`，显式传 `-WithBeat:$false`
  - `market` worker 负责 `market_sync,news_ingest`
  - `snapshot` worker 负责 `snapshot_capture,snapshot_aggregate,snapshot_cleanup`
  - `ai` worker 负责 `news_embedding,ai_analysis`
  - 当前默认每个 worker 都是 `threads` 池，`--concurrency 4`
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
  - `start_celery.*` uses `Targets market,snapshot,ai` by default
  - `all` now means the same three dedicated workers: `market`, `snapshot`, and `ai`
  - Windows `start_celery.ps1` defaults to `-Targets market,snapshot,ai -WithBeat -Pool threads -Concurrency 4`
  - To start only the worker without `beat`, pass `-WithBeat:$false`
  - `market` handles `market_sync,news_ingest`
  - `snapshot` handles `snapshot_capture,snapshot_aggregate,snapshot_cleanup`
  - `ai` handles `news_embedding,ai_analysis`
  - Each worker now defaults to `threads` with `--concurrency 4`
- Current RabbitMQ / Celery behavior:
  - `beat` publishes one forced `market_sync` refresh on startup
  - periodic tasks carry `expires`
  - `market_sync` and `snapshot_capture` queues use RabbitMQ `x-message-ttl`
- `resource/scripts/macos/` now keeps only:
  - `bootstrap_first_run_conda.sh`
  - `install_python_deps_conda.sh`
  - `start_celery.sh`
  - `stop_celery.sh`
