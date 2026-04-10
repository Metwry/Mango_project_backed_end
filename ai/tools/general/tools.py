from __future__ import annotations

import json
from functools import lru_cache
from zoneinfo import ZoneInfo

from django.contrib.auth import get_user_model
from django.utils import timezone
from langchain_core.tools import tool
from pydantic import BaseModel, ConfigDict, Field

from ai.agent.runtime_context import get_agent_context
from ai.services.general.position_summary import PositionSummaryService
from accounts.services import get_account_summary as query_account_summary
from accounts.services import get_recent_transaction as query_recent_transaction
from investment.services.query_service import get_recent_trades as query_recent_trades
from snapshot.services.query_service import get_account_trend as query_account_trend
from snapshot.services.query_service import get_position_trend as query_position_trend


def _get_current_user():
    user_id = get_agent_context().get("user_id")
    if not user_id:
        raise ValueError("user_id is required")
    return get_user_model().objects.get(id=int(user_id))


class PositionSummaryQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    query: str = Field(description="用户关于持仓的原始问题")
    symbols: list[str] | None = Field(default=None, description="可选的标的列表，例如 ['BTC', 'BNB']")


class AccountSummaryQuery(BaseModel):
    model_config = ConfigDict(extra="allow")


class AccountTrendQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    start: str | None = Field(default=None, description="起始时间")
    end: str | None = Field(default=None, description="结束时间")
    account_ids: list[int] | list[str] | None = Field(default=None, description="可选的账户 ID 列表")
    fields: list[str] | None = Field(default=None, description="可选字段列表")


class PositionTrendQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    start: str | None = Field(default=None, description="起始时间")
    end: str | None = Field(default=None, description="结束时间")
    symbols: list[str] | None = Field(default=None, description="可选的标的列表")
    fields: list[str] | None = Field(default=None, description="可选字段列表")


class RecentTradesQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    symbols: list[str] | None = Field(default=None, description="可选的标的列表")
    limit: int | None = Field(default=None, description="可选的返回条数，默认 10")


class RecentTransactionQuery(BaseModel):
    model_config = ConfigDict(extra="allow")
    account_ids: list[int] | list[str] | None = Field(default=None, description="可选的账户 ID 列表")
    limit: int | None = Field(default=None, description="可选的返回条数，默认 10")


@lru_cache(maxsize=1)
def _position_summary_service() -> PositionSummaryService:
    return PositionSummaryService()


@tool
def get_current_time() -> str:
    """返回当前本地时间、日期和时区。涉及相对时间时优先调用。"""
    now = timezone.now().astimezone(ZoneInfo("Asia/Shanghai"))
    payload = {
        "current_datetime": now.isoformat(),
        "current_date": now.date().isoformat(),
        "timezone": "Asia/Shanghai",
        "weekday": now.strftime("%A"),
    }
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=PositionSummaryQuery)
def get_user_position(**kwargs) -> str:
    """返回用户当前持仓的结构化摘要数据。"""
    query = str(kwargs.get("query") or "").strip()
    payload = _position_summary_service().summarize(
        user_id=int(_get_current_user().id),
        query=query,
        symbols=kwargs.get("symbols"),
    )
    return json.dumps(payload, ensure_ascii=False)


@tool(args_schema=AccountSummaryQuery)
def get_account_summary(**kwargs) -> dict:
    """返回用户当前所有账户的结构化摘要数据。"""
    return query_account_summary(user=_get_current_user())


@tool(args_schema=AccountTrendQuery)
def get_account_trend(**kwargs) -> dict:
    """返回用户账户在指定时间段内的时间序列与趋势指标。"""
    return query_account_trend(
        user=_get_current_user(),
        start=kwargs.get("start"),
        end=kwargs.get("end"),
        account_ids=kwargs.get("account_ids"),
        fields=kwargs.get("fields"),
    )


@tool(args_schema=PositionTrendQuery)
def get_position_trend(**kwargs) -> dict:
    """返回用户持仓在指定时间段内的时间序列与趋势指标。"""
    return query_position_trend(
        user=_get_current_user(),
        start=kwargs.get("start"),
        end=kwargs.get("end"),
        symbols=kwargs.get("symbols"),
        fields=kwargs.get("fields"),
    )


@tool(args_schema=RecentTradesQuery)
def get_recent_trades(**kwargs) -> dict:
    """返回用户最近的投资交易记录。"""
    return query_recent_trades(
        user=_get_current_user(),
        symbols=kwargs.get("symbols"),
        limit=kwargs.get("limit"),
    )


@tool(args_schema=RecentTransactionQuery)
def get_recent_transaction(**kwargs) -> dict:
    """返回用户最近的账户交易记录，包括转账和手工记账。"""
    return query_recent_transaction(
        user=_get_current_user(),
        account_ids=kwargs.get("account_ids"),
        limit=kwargs.get("limit"),
    )
