from __future__ import annotations

from openai import OpenAI

from ai.llmmodels.base_model import BaseEmbeddingModel, EmbeddingResult


class OpenAIEmbeddingModel(BaseEmbeddingModel):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        task_config: dict,
    ) -> None:
        super().__init__(model_name=model_name, api_key=api_key, task_config=task_config)
        self.client = OpenAI(api_key=api_key)

    def embed(self, *, texts: list[str]) -> EmbeddingResult:
        response = self.client.embeddings.create(
            model=self.model_name,
            input=texts,
        )
        vectors = [item.embedding for item in response.data]
        return EmbeddingResult(model_name=self.model_name, vectors=vectors)
