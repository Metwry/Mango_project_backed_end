from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from ai.agent.runtime_context import get_agent_context
from ai.services.account_trend import get_account_trend as load_account_trend


class AccountTrendQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    start: str | None = Field(default=None, description="起始时间")
    end: str | None = Field(default=None, description="结束时间")
    account_ids: list[int] | list[str] | None = Field(default=None, description="可选的账户 ID 列表")
    fields: list[str] | None = Field(default=None, description="可选字段列表")


class AccountTrendTool:

    def get_account_trend(self, request: dict) -> dict:
        context = get_agent_context()
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        return load_account_trend(
            user_id=user_id,
            start=request.get("start"),
            end=request.get("end"),
            account_ids=request.get("account_ids"),
            fields=request.get("fields"),
        )
