from __future__ import annotations

from pydantic import BaseModel, Field

from ai.services.position_data import get_position_data as load_position_data


class PositionDataQuery(BaseModel):
    symbols: list[str] | None = Field(default=None, description="可选的标的列表，例如 ['BTC', 'BNB']")


class PositionDataTool:

    def get_position_data(self, request: dict) -> dict:
        context = request.get("context") or {}
        user_id = context.get("user_id")
        if not user_id:
            raise ValueError("user_id is required")
        return load_position_data(user_id=user_id, symbols=request.get("symbols"))
