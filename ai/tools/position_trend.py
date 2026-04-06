from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai.agent.runtime_context import get_agent_context
from ai.services.position_trend import get_position_trend as load_position_trend


class PositionTrendQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    start: str | None = Field(default=None, description="起始时间")
    end: str | None = Field(default=None, description="结束时间")
    symbols: list[str] | None = Field(default=None, description="可选的标的列表")
    fields: list[str] | None = Field(default=None, description="可选字段列表")


class PositionTrendTool:

    def get_position_trend(self, request: dict) -> dict:
        context = get_agent_context()
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        return load_position_trend(
            user_id=user_id,
            start=request.get("start"),
            end=request.get("end"),
            symbols=request.get("symbols"),
            fields=request.get("fields"),
        )
