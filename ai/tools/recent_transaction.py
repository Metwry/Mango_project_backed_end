from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai.agent.runtime_context import get_agent_context
from ai.services.recent_transaction import get_recent_transaction as load_recent_transaction


class RecentTransactionQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    account_ids: list[int] | list[str] | None = Field(default=None, description="可选的账户 ID 列表")
    limit: int | None = Field(default=None, description="可选的返回条数，默认 10")


class RecentTransactionTool:

    def get_recent_transaction(self, request: dict) -> dict:
        context = get_agent_context()
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        return load_recent_transaction(
            user_id=user_id,
            account_ids=request.get("account_ids"),
            limit=request.get("limit"),
        )
