from __future__ import annotations

import os
from typing import Any

from ai.config import get_provider_config
from ai.llmmodels.aliyun_chat import AliyunChatModel
from ai.llmmodels.aliyun_embedding import AliyunEmbeddingModel
from ai.llmmodels.base_model import BaseChatModel, BaseEmbeddingModel
from ai.llmmodels.openai_chat import OpenAIChatModel
from ai.llmmodels.openai_embedding import OpenAIEmbeddingModel


class LLMModelFactory:
    @staticmethod
    def create_chat_model(
        *,
        provider_name: str,
        model_name: str,
        task_config: dict[str, Any],
    ) -> BaseChatModel:
        resolved_api_key = LLMModelFactory.resolve_api_key(provider_name=provider_name)
        resolved_base_url = LLMModelFactory.resolve_base_url(provider_name=provider_name)
        if provider_name == "aliyun":
            return AliyunChatModel(
                model_name=model_name,
                api_key=resolved_api_key,
                task_config=task_config,
            )
        if provider_name in {"openai", "ollama"}:
            return OpenAIChatModel(
                model_name=model_name,
                api_key=resolved_api_key,
                task_config=task_config,
                base_url=resolved_base_url,
            )
        raise ValueError(f"不支持的模型提供商: {provider_name}")

    @staticmethod
    def create_embedding_model(
        *,
        provider_name: str,
        model_name: str,
        task_config: dict[str, Any],
    ) -> BaseEmbeddingModel:
        resolved_api_key = LLMModelFactory.resolve_api_key(provider_name=provider_name)
        if provider_name == "aliyun":
            return AliyunEmbeddingModel(
                model_name=model_name,
                api_key=resolved_api_key,
                task_config=task_config,
            )
        if provider_name == "openai":
            return OpenAIEmbeddingModel(
                model_name=model_name,
                api_key=resolved_api_key,
                task_config=task_config,
            )
        raise ValueError(f"不支持的模型提供商: {provider_name}")

    @staticmethod
    def resolve_api_key(*, provider_name: str) -> str:
        provider_config = get_provider_config(provider_name)
        api_key_env = str(provider_config.get("api_key_env", "")).strip()
        if not api_key_env:
            return ""
        resolved_api_key = os.getenv(api_key_env, "").strip()
        if not resolved_api_key:
            raise ValueError(
                f"未配置 {api_key_env}，无法执行 {provider_name} 模型分析。"
            )
        return resolved_api_key

    @staticmethod
    def resolve_base_url(*, provider_name: str) -> str | None:
        provider_config = get_provider_config(provider_name)
        base_url_env = str(provider_config.get("base_url_env", "")).strip()
        if not base_url_env:
            return None
        resolved_base_url = os.getenv(base_url_env, "").strip()
        if not resolved_base_url:
            raise ValueError(
                f"未配置 {base_url_env}，无法执行 {provider_name} 模型分析。"
            )
        return resolved_base_url
