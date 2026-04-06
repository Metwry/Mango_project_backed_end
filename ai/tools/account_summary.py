from __future__ import annotations

from pydantic import BaseModel, ConfigDict

from ai.agent.runtime_context import get_agent_context
from ai.services.account_summary import get_account_summary as load_account_summary


class AccountSummaryQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    pass


class AccountSummaryTool:

    def get_account_summary(self, request: dict) -> dict:
        context = get_agent_context()
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        return load_account_summary(user_id=user_id)
