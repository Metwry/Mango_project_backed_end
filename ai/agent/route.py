from __future__ import annotations

import json
from typing import Literal

from ai.config import get_prompt_text
from ai.llmmodels.model_factory import LLMModelFactory


AgentRoute = Literal["GENERAL", "NEWS", "TRADING"]


class RouteAgent:
    def __init__(self) -> None:
        self.model = LLMModelFactory.create_chat_model(task_name="route_agent")
        self.prompt = get_prompt_text("route_agent")

    def execute(self, *, query: str, has_active_trade_draft: bool) -> AgentRoute:
        rendered_prompt = self.prompt.format(
            query=query.strip(),
            has_active_trade_draft="true" if has_active_trade_draft else "false",
        )
        response = self.model.invoke(rendered_prompt)
        content = getattr(response, "content", response)
        text = content if isinstance(content, str) else str(content or "")
        payload = self._parse_json(text)
        route = str(payload["route"]).strip().upper()
        if route in {"TRADING", "NEWS", "GENERAL"}:
            return route
        raise ValueError(f"Unsupported route returned by route agent: {route}")

    @staticmethod
    def _parse_json(text: str) -> dict:
        stripped = text.strip()
        if stripped.startswith("```"):
            lines = stripped.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            stripped = "\n".join(lines).strip()
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("Route agent must return a JSON object.")
        return payload
