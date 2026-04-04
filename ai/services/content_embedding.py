from __future__ import annotations

from dataclasses import dataclass
import os

from ai.config import get_embedding_model_config, get_embedding_task_config
from ai.llmmodels import LLMModelFactory
from ai.llmmodels.llm_runtime import embed_texts


@dataclass(slots=True)
class EmbeddingResult:
    model_name: str
    vectors: list[list[float]]


class EmbeddingService:
    def embed(
        self,
        *,
        task_name: str,
        texts: list[str],
        config_overrides: dict | None = None,
    ) -> EmbeddingResult:
        task_config = get_embedding_task_config(task_name)
        if config_overrides:
            task_config.update(config_overrides)

        model_config = get_embedding_model_config(task_name)
        provider_name = model_config.provider
        model_name = model_config.model
        api_key = os.environ[model_config.api_key_env]
        embedding_model = LLMModelFactory.create_embedding_model(
            task_name=task_name,
        )
        if not texts:
            return EmbeddingResult(model_name=model_name, vectors=[])

        batch_size = int(model_config.batch_size)
        if batch_size <= 0:
            raise ValueError("embedding batch_size 必须大于 0")

        vectors: list[list[float]] = []
        for start in range(0, len(texts), batch_size):
            batch = texts[start : start + batch_size]
            batch_vectors = embed_texts(
                embedding_client=embedding_model,
                provider_name=provider_name,
                model_name=model_name,
                task_config={**task_config, "batch_size": model_config.batch_size},
                texts=batch,
                api_key=api_key,
            )
            vectors.extend(batch_vectors)

        return EmbeddingResult(model_name=model_name, vectors=vectors)
