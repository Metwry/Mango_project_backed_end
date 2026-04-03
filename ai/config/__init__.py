from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml


CONFIG_DIR = Path(__file__).resolve().parent
PROMPTS_DIR = CONFIG_DIR.parent / "prompts"
PROVIDERS_CONFIG_PATH = CONFIG_DIR / "providers.yaml"
CHAT_CONFIG_PATH = CONFIG_DIR / "chat_tasks.yaml"
EMBEDDING_CONFIG_PATH = CONFIG_DIR / "embedding_tasks.yaml"


class ConfigObject(dict):
    def __getattr__(self, name: str) -> Any:
        try:
            return self[name]
        except KeyError as exc:
            raise AttributeError(name) from exc


def _to_config_object(value: Any) -> Any:
    if isinstance(value, dict):
        return ConfigObject({key: _to_config_object(item) for key, item in value.items()})
    if isinstance(value, list):
        return [_to_config_object(item) for item in value]
    return value


@lru_cache(maxsize=1)
def load_providers_config() -> ConfigObject:
    with PROVIDERS_CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return _to_config_object(yaml.safe_load(fp))


@lru_cache(maxsize=1)
def load_chat_config() -> ConfigObject:
    with CHAT_CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return _to_config_object(yaml.safe_load(fp))


@lru_cache(maxsize=1)
def load_embedding_config() -> ConfigObject:
    with EMBEDDING_CONFIG_PATH.open("r", encoding="utf-8") as fp:
        return _to_config_object(yaml.safe_load(fp))


def get_chat_task_config(task_name: str) -> ConfigObject:
    return load_chat_config().tasks[task_name]


def get_analysis_task_config(task_name: str) -> ConfigObject:
    return get_chat_task_config(task_name)


def get_embedding_task_config(task_name: str) -> ConfigObject:
    return load_embedding_config().tasks[task_name]


def get_provider_config(provider_name: str) -> ConfigObject:
    return load_providers_config().providers[provider_name]


def get_chat_model_config(task_name: str) -> ConfigObject:
    task_config = get_chat_task_config(task_name)
    provider_config = get_provider_config(task_config.provider)
    model_config = provider_config.chat_models[task_config.model]
    return ConfigObject(
        {
            "provider": task_config.provider,
            "model": task_config.model,
            "api_key_env": provider_config.api_key_env,
            "temperature": model_config.temperature,
            "timeout": model_config.timeout,
            "max_retries": model_config.max_retries,
            "max_tokens": getattr(task_config, "max_tokens", model_config.max_tokens),
            "reasoning_effort": getattr(task_config, "reasoning_effort", getattr(model_config, "reasoning_effort", None)),
            "verbosity": getattr(task_config, "verbosity", getattr(model_config, "verbosity", None)),
            "enable_thinking": getattr(task_config, "enable_thinking", getattr(model_config, "enable_thinking", None)),
            "thinking_budget": getattr(task_config, "thinking_budget", getattr(model_config, "thinking_budget", None)),
        }
    )


def get_embedding_model_config(task_name: str) -> ConfigObject:
    task_config = get_embedding_task_config(task_name)
    provider_config = get_provider_config(task_config.provider)
    model_config = provider_config.embedding_models[task_config.model]
    return ConfigObject(
        {
            "provider": task_config.provider,
            "model": task_config.model,
            "api_key_env": provider_config.api_key_env,
            "batch_size": getattr(task_config, "batch_size", model_config.batch_size),
        }
    )


def get_prompt_path(prompt_file: str) -> Path:
    return PROMPTS_DIR / prompt_file


def get_prompt_text(task_name: str) -> str:
    task_config = get_chat_task_config(task_name)
    return get_prompt_path(task_config.prompt_file).read_text(encoding="utf-8")
