from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from time import perf_counter
from typing import Any

from ai.config import get_analysis_task_config, get_prompt_path
from ai.services.ai_log import ai_log_scope
from ai.llmmodels import LLMModelFactory


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
        with ai_log_scope(
            event="analysis",
            task_name=task_name,
            prompt_name=prompt_name,
            provider=provider_name,
            model_name=model_name,
        ) as scope:
            step_started_at = perf_counter()
            prompt_text = prompt_path.read_text(encoding="utf-8")
            rendered_prompt = prompt_text.format(**variables)
            prompt_prepare_ms = (perf_counter() - step_started_at) * 1000
            scope.set(
                prompt_prepare_ms=round(prompt_prepare_ms, 2),
                prompt_length=len(rendered_prompt),
            )

            step_started_at = perf_counter()
            chat_model = LLMModelFactory.create_chat_model(
                provider_name=provider_name,
                model_name=model_name,
                task_config=task_config,
            )
            raw_text = chat_model.generate(prompt_text=rendered_prompt).raw_text
            model_generate_ms = (perf_counter() - step_started_at) * 1000
            scope.set(
                model_generate_ms=round(model_generate_ms, 2),
                output_length=len(raw_text),
            )

            if not task_config.get("expects_json", True):
                result = AnalysisResult(
                    task_name=task_name,
                    prompt_name=prompt_name,
                    model_name=model_name,
                    raw_text=raw_text,
                    data={},
                )
                return result

            step_started_at = perf_counter()
            parsed = json.loads(self._normalize_json_text(raw_text))
            json_parse_ms = (perf_counter() - step_started_at) * 1000
            result = AnalysisResult(
                task_name=task_name,
                prompt_name=prompt_name,
                model_name=model_name,
                raw_text=raw_text,
                data=parsed,
            )
            scope.set(json_parse_ms=round(json_parse_ms, 2))
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
