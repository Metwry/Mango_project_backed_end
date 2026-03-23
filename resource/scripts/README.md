# Scripts Directory / 脚本目录

## 中文

- 定位：存放环境初始化、Conda Python 依赖安装，以及 Celery 启停脚本。
- Python 依赖安装统一基于 conda 环境，不再提供普通 `venv` 安装脚本。
- 当前路径：`resource/scripts/`
- 目录划分：
  - `resource/scripts/windows/`：PowerShell 和 Batch 脚本
  - `resource/scripts/unix/`：Unix shell 脚本目录
  - `resource/scripts/macos/`：macOS 专用脚本目录
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
  - `resource/scripts/windows/`: PowerShell and Batch scripts
  - `resource/scripts/unix/`: Unix shell scripts
  - `resource/scripts/macos/`: macOS-specific scripts
- `resource/scripts/macos/` now keeps only:
  - `bootstrap_first_run_conda.sh`
  - `install_python_deps_conda.sh`
  - `start_celery.sh`
  - `stop_celery.sh`
