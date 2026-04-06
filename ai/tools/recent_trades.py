from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai.agent.runtime_context import get_agent_context
from ai.services.recent_trades import get_recent_trades as load_recent_trades


class RecentTradesQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbols: list[str] | None = Field(default=None, description="可选的标的列表")
    limit: int | None = Field(default=None, description="可选的返回条数，默认 10")


class RecentTradesTool:

    def get_recent_trades(self, request: dict) -> dict:
        context = get_agent_context()
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        return load_recent_trades(
            user_id=user_id,
            symbols=request.get("symbols"),
            limit=request.get("limit"),
        )
