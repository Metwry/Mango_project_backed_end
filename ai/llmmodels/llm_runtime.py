from __future__ import annotations

import http.client
import ssl
import time
from typing import Any

import requests

RETRYABLE_EXCEPTIONS = (
    requests.exceptions.ConnectionError,
    requests.exceptions.SSLError,
    ssl.SSLError,
    http.client.RemoteDisconnected,
    ConnectionResetError,
    TimeoutError,
)


def coerce_chat_content(content: Any) -> str:
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts: list[str] = []
        for item in content:
            if isinstance(item, str):
                parts.append(item)
                continue
            if isinstance(item, dict):
                text = item.get("text")
                if text:
                    parts.append(str(text))
        return "".join(parts)
    return str(content or "")
def embed_texts(
    *,
    embedding_client: Any,
    provider_name: str,
    model_name: str,
    task_config: dict[str, Any],
    texts: list[str],
    api_key: str = "",
) -> list[list[float]]:
    if provider_name == "openai":
        response = embedding_client.embeddings.create(
            model=model_name,
            input=texts,
        )
        return [item.embedding for item in response.data]

    if provider_name == "aliyun":
        response = _invoke_with_optional_retries(
            provider_name=provider_name,
            task_config=task_config,
            invoke=lambda: embedding_client.call(
                model=model_name,
                input=texts,
                api_key=api_key,
                dimension=1536,
            ),
        )
        if response.status_code != 200:
            raise ValueError(
                f"aliyun embedding 调用失败: status_code={response.status_code}, message={response.message}"
            )
        embeddings = response.output.get("embeddings", [])
        return [item["embedding"] for item in embeddings]

    raise ValueError(f"不支持的 embedding provider: {provider_name}")


def _invoke_with_optional_retries(
    *,
    provider_name: str,
    task_config: dict[str, Any],
    invoke,
):
    if provider_name != "aliyun":
        return invoke()

    attempts = int(task_config.get("network_retry_attempts", 3))
    base_delay = float(task_config.get("network_retry_base_delay", 1))
    last_exc: Exception | None = None
    for attempt in range(1, attempts + 1):
        try:
            return invoke()
        except RETRYABLE_EXCEPTIONS as exc:
            last_exc = exc
            if attempt >= attempts:
                break
            time.sleep(base_delay * (2 ** (attempt - 1)))
    if last_exc is not None:
        raise last_exc
    raise RuntimeError("invoke failed without exception")
