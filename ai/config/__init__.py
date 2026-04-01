from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = CONFIG_DIR.parent / "prompts"
ANALYSIS_CONFIG_PATH = CONFIG_DIR / "analysis_tasks.yaml"
CHAT_CONFIG_PATH = CONFIG_DIR / "chat_tasks.yaml"
EMBEDDING_CONFIG_PATH = CONFIG_DIR / "embedding_tasks.yaml"


@lru_cache(maxsize=1)
def load_analysis_config() -> dict[str, Any]:
    with ANALYSIS_CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


@lru_cache(maxsize=1)
def load_chat_config() -> dict[str, Any]:
    with CHAT_CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


@lru_cache(maxsize=1)
def load_embedding_config() -> dict[str, Any]:
    with EMBEDDING_CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return yaml.safe_load(fp) or {}


def get_analysis_task_config(task_name: str) -> dict[str, Any]:
    for config in (load_analysis_config(), load_chat_config()):
        defaults = dict(config.get("defaults", {}))
        task_config = config.get("tasks", {}).get(task_name)
        if task_config:
            merged = {**defaults, **task_config}
            merged["task_name"] = task_name
            return merged
    raise KeyError(f"未找到分析任务配置: {task_name}")


def get_embedding_task_config(task_name: str) -> dict[str, Any]:
    config = load_embedding_config()
    defaults = dict(config.get("defaults", {}))
    task_config = config.get("tasks", {}).get(task_name)
    if not task_config:
        raise KeyError(f"未找到嵌入任务配置: {task_name}")
    merged = {**defaults, **task_config}
    merged["task_name"] = task_name
    return merged


def get_provider_config(provider_name: str) -> dict[str, Any]:
    for config in (load_analysis_config(), load_chat_config()):
        provider_config = config.get("providers", {}).get(provider_name)
        if provider_config:
            return dict(provider_config)
    raise KeyError(f"未找到模型提供商配置: {provider_name}")


def get_prompt_path(prompt_file: str) -> Path:
    return PROMPTS_DIR / prompt_file
