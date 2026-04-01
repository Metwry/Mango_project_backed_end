from __future__ import annotations

import http.client
import ssl
import time

import requests
from langchain_community.chat_models import ChatTongyi
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ai.llmmodels.base_model import BaseChatModel, ChatGenerationResult


class AliyunChatModel(BaseChatModel):
    RETRYABLE_EXCEPTIONS = (
        requests.exceptions.ConnectionError,
        requests.exceptions.SSLError,
        ssl.SSLError,
        http.client.RemoteDisconnected,
        ConnectionResetError,
        TimeoutError,
    )

    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        task_config: dict,
    ) -> None:
        super().__init__(model_name=model_name, api_key=api_key, task_config=task_config)
        model_kwargs: dict[str, object] = {}
        if task_config.get("enable_thinking") is not None:
            model_kwargs["enable_thinking"] = bool(task_config.get("enable_thinking"))
        if task_config.get("thinking_budget") is not None:
            model_kwargs["thinking_budget"] = task_config.get("thinking_budget")
        if task_config.get("max_tokens") is not None:
            model_kwargs["max_tokens"] = task_config.get("max_tokens")

        self.llm = ChatTongyi(
            model=model_name,
            temperature=task_config.get("temperature", 0),
            timeout=task_config.get("timeout", 60),
            max_retries=task_config.get("max_retries", 2),
            api_key=api_key,
            model_kwargs=model_kwargs,
        )

    def generate(self, *, prompt_text: str) -> ChatGenerationResult:
        prompt = ChatPromptTemplate.from_messages([("user", prompt_text)])
        chain = prompt | self.llm | StrOutputParser()
        raw_text = self._invoke_with_retries(chain=chain)
        return ChatGenerationResult(model_name=self.model_name, raw_text=raw_text)

    def _invoke_with_retries(self, *, chain) -> str:
        attempts = int(self.task_config.get("network_retry_attempts", 3))
        base_delay = float(self.task_config.get("network_retry_base_delay", 1))
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return chain.invoke({})
            except self.RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                time.sleep(base_delay * (2 ** (attempt - 1)))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("aliyun invoke failed without exception")
