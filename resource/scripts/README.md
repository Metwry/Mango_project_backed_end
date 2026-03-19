# Scripts Directory / 脚本目录

## 中文

- 定位：存放环境初始化、依赖安装、Web 和 Celery 启停脚本。
- Python 依赖安装统一基于 conda 环境，不再提供普通 `venv` 安装脚本。
- 当前路径：`resource/scripts/`
- 目录划分：
  - `resource/scripts/windows/`：PowerShell 和 Batch 脚本
  - `resource/scripts/unix/`：Unix shell 脚本目录
  - `resource/scripts/macos/`：macOS 专用脚本目录
- 使用建议：每个子目录各自包含该平台会用到的脚本，不依赖“通用入口”跳转。

## English

- Role: contains environment bootstrap, dependency installation, and web/Celery lifecycle scripts.
- Python dependency installation is conda-only; plain `venv` installers are no longer provided.
- Current path: `resource/scripts/`
- Layout:
  - `resource/scripts/windows/`: PowerShell and Batch scripts
  - `resource/scripts/unix/`: Unix shell scripts
  - `resource/scripts/macos/`: macOS-specific scripts
- Recommendation: each platform directory should carry the scripts it uses directly instead of relying on a shared entrypoint.
