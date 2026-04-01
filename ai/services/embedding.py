from __future__ import annotations

from time import perf_counter

from ai.config import get_embedding_task_config
from ai.llmmodels import EmbeddingResult, LLMModelFactory
from ai.services.ai_log import ai_log_scope


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

        provider_name = str(task_config["provider"]).strip()
        provider_models = task_config["models"]
        model_name = str(provider_models[provider_name]).strip()
        with ai_log_scope(
            event="embedding",
            task_name=task_name,
            provider=provider_name,
            model_name=model_name,
            text_count=len(texts),
        ) as scope:
            embedding_model = LLMModelFactory.create_embedding_model(
                provider_name=provider_name,
                model_name=model_name,
                task_config=task_config,
            )
            if not texts:
                result = EmbeddingResult(model_name=model_name, vectors=[])
                scope.set(vector_count=0)
                return result

            batch_size = int(task_config.get("batch_size", len(texts)))
            if batch_size <= 0:
                raise ValueError("embedding batch_size 必须大于 0")

            vectors: list[list[float]] = []
            batch_call_ms = 0.0
            for start in range(0, len(texts), batch_size):
                batch = texts[start : start + batch_size]
                step_started_at = perf_counter()
                batch_result = embedding_model.embed(texts=batch)
                batch_call_ms += (perf_counter() - step_started_at) * 1000
                vectors.extend(batch_result.vectors)

            result = EmbeddingResult(model_name=model_name, vectors=vectors)
            scope.set(
                vector_count=len(vectors),
                batch_size=batch_size,
                batch_count=(len(texts) + batch_size - 1) // batch_size,
                batch_call_ms=round(batch_call_ms, 2),
            )
            return result
