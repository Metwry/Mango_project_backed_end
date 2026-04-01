from __future__ import annotations

from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI

from ai.llmmodels.base_model import BaseChatModel, ChatGenerationResult


class OpenAIChatModel(BaseChatModel):
    def __init__(
        self,
        *,
        model_name: str,
        api_key: str,
        task_config: dict,
        base_url: str | None = None,
    ) -> None:
        super().__init__(model_name=model_name, api_key=api_key, task_config=task_config)
        llm_kwargs = {
            "model": model_name,
            "temperature": task_config.get("temperature", 0),
            "timeout": task_config.get("timeout", 60),
            "max_retries": task_config.get("max_retries", 2),
        }
        if api_key:
            llm_kwargs["api_key"] = api_key

        reasoning_effort = task_config.get("reasoning_effort")
        if reasoning_effort is not None:
            llm_kwargs["reasoning_effort"] = reasoning_effort

        verbosity = task_config.get("verbosity")
        if verbosity is not None:
            llm_kwargs["verbosity"] = verbosity

        max_tokens = task_config.get("max_tokens")
        if max_tokens is not None:
            llm_kwargs["max_tokens"] = max_tokens

        if base_url:
            llm_kwargs["base_url"] = base_url

        self.llm = ChatOpenAI(
            **llm_kwargs,
        )

    def generate(self, *, prompt_text: str) -> ChatGenerationResult:
        prompt = ChatPromptTemplate.from_messages([("user", prompt_text)])
        chain = prompt | self.llm | StrOutputParser()
        raw_text = chain.invoke({})
        return ChatGenerationResult(model_name=self.model_name, raw_text=raw_text)
