from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai.agent.runtime_context import get_agent_context
from ai.services.position_summary import PositionSummaryService


class PositionSummaryQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    query: str = Field(description="用户关于持仓的原始问题")
    symbols: list[str] | None = Field(default=None, description="可选的标的列表，例如 ['BTC', 'BNB']")


class UserPositionSummaryTool:

    def __init__(self) -> None:
        self.service = PositionSummaryService()

    def get_position_summary(self, request: dict) -> str:
        context = get_agent_context()
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        query = str(request.get("query", "")).strip()
        symbols = request.get("symbols")
        return self.service.summarize(user_id=user_id, query=query, symbols=symbols)
