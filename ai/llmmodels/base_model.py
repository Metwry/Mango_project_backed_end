from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any


@dataclass(slots=True)
class ChatGenerationResult:
    model_name: str
    raw_text: str


@dataclass(slots=True)
class EmbeddingResult:
    model_name: str
    vectors: list[list[float]]


class BaseChatModel(ABC):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        task_config: dict[str, Any],
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.task_config = task_config

    @abstractmethod
    def generate(self, *, prompt_text: str) -> ChatGenerationResult:
        raise NotImplementedError


class BaseEmbeddingModel(ABC):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        task_config: dict[str, Any],
    ) -> None:
        self.model_name = model_name
        self.api_key = api_key
        self.task_config = task_config

    @abstractmethod
    def embed(self, *, texts: list[str]) -> EmbeddingResult:
        raise NotImplementedError
