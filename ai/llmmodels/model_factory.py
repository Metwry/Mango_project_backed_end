from __future__ import annotations

import os
from typing import Any

import dashscope
from langchain_community.chat_models import ChatTongyi
from langchain_openai import ChatOpenAI
from openai import OpenAI

from ai.config import (
    get_chat_model_config,
    get_embedding_model_config,
)


def build_chat_model(config: dict[str, Any]) -> Any:
    if config.provider == "aliyun":
        return ChatTongyi(
            model=config.model,
            temperature=config.temperature,
            timeout=config.timeout,
            max_retries=config.max_retries,
            streaming=bool(getattr(config, "streaming", False)),
            disable_streaming="tool_calling",
            api_key=os.environ[config.api_key_env],
            model_kwargs={
                "enable_thinking": config.enable_thinking,
                "thinking_budget": config.thinking_budget,
                "max_tokens": config.max_tokens,
            },
        )

    return ChatOpenAI(
        model=config.model,
        temperature=config.temperature,
        timeout=config.timeout,
        max_retries=config.max_retries,
        api_key=os.environ[config.api_key_env],
        reasoning_effort=config.reasoning_effort,
        verbosity=config.verbosity,
        max_tokens=config.max_tokens,
    )


def build_embedding_model(config: dict[str, Any]) -> Any:
    if config.provider == "aliyun":
        return dashscope.TextEmbedding
    return OpenAI(api_key=os.environ[config.api_key_env])


class LLMModelFactory:
    @staticmethod
    def create_chat_model(
        *,
        task_name: str,
    ) -> Any:
        return build_chat_model(get_chat_model_config(task_name))

    @staticmethod
    def create_embedding_model(
        *,
        task_name: str,
    ) -> Any:
        return build_embedding_model(get_embedding_model_config(task_name))
