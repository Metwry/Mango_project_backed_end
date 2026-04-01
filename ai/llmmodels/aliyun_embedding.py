from __future__ import annotations

import http.client
import ssl
import time

import dashscope
import requests

from ai.llmmodels.base_model import BaseEmbeddingModel, EmbeddingResult


class AliyunEmbeddingModel(BaseEmbeddingModel):
    RETRYABLE_EXCEPTIONS = (
        requests.exceptions.ConnectionError,
        requests.exceptions.SSLError,
        ssl.SSLError,
        http.client.RemoteDisconnected,
        ConnectionResetError,
        TimeoutError,
    )

    def embed(self, *, texts: list[str]) -> EmbeddingResult:
        response = self._call_with_retries(texts=texts)
        if response.status_code != 200:
            raise ValueError(
                f"aliyun embedding 调用失败: status_code={response.status_code}, message={response.message}"
            )

        embeddings = response.output.get("embeddings", [])
        vectors = [item["embedding"] for item in embeddings]
        return EmbeddingResult(model_name=self.model_name, vectors=vectors)

    def _call_with_retries(self, *, texts: list[str]):
        attempts = int(self.task_config.get("network_retry_attempts", 3))
        base_delay = float(self.task_config.get("network_retry_base_delay", 1))
        last_exc: Exception | None = None
        for attempt in range(1, attempts + 1):
            try:
                return dashscope.TextEmbedding.call(
                    model=self.model_name,
                    input=texts,
                    api_key=self.api_key,
                    dimension=1536,
                )
            except self.RETRYABLE_EXCEPTIONS as exc:
                last_exc = exc
                if attempt >= attempts:
                    break
                time.sleep(base_delay * (2 ** (attempt - 1)))
        if last_exc is not None:
            raise last_exc
        raise RuntimeError("aliyun embedding invoke failed without exception")
