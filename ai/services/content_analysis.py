from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ai.config import get_analysis_task_config, get_prompt_path
from ai.llmmodels.model_factory import LLMModelFactory
from ai.llmmodels.llm_runtime import _invoke_with_optional_retries, coerce_chat_content


@dataclass(slots=True)
class AnalysisResult:
    task_name: str
    prompt_name: str
    model_name: str
    raw_text: str
    data: dict[str, Any]


class AnalysisService:
    def analyze(
        self,
        *,
        task_name: str,
        variables: dict[str, Any],
        config_overrides: dict[str, Any] | None = None,
    ) -> AnalysisResult:
        task_config = get_analysis_task_config(task_name)
        if config_overrides:
            task_config.update(config_overrides)

        provider_name = str(task_config["provider"]).strip()
        model_name = str(task_config["model"]).strip()

        prompt_path = get_prompt_path(task_config["prompt_file"])
        prompt_name = Path(prompt_path).stem
        prompt_text = prompt_path.read_text(encoding="utf-8")
        rendered_prompt = prompt_text.format(**variables)

        chat_model = LLMModelFactory.create_chat_model(
            task_name=task_name,
        )
        response = _invoke_with_optional_retries(
            provider_name=provider_name,
            task_config=task_config,
            invoke=lambda: chat_model.invoke(rendered_prompt),
        )
        raw_text = coerce_chat_content(getattr(response, "content", response))

        if not task_config.get("expects_json", True):
            result = AnalysisResult(
                task_name=task_name,
                prompt_name=prompt_name,
                model_name=model_name,
                raw_text=raw_text,
                data={},
            )
            return result

        parsed = json.loads(self._normalize_json_text(raw_text))
        result = AnalysisResult(
            task_name=task_name,
            prompt_name=prompt_name,
            model_name=model_name,
            raw_text=raw_text,
            data=parsed,
        )
        return result

    @staticmethod
    def _normalize_json_text(raw_text: str) -> str:
        text = raw_text.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        return text
