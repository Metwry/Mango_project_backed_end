from functools import lru_cache

from langchain_core.tools import tool
from ai.rag.newsSummaryService import NewsSummaryQuery, NewsSummaryService
from ai.tools.account_trend import AccountTrendQuery, AccountTrendTool
from ai.tools.account_summary import AccountSummaryQuery, AccountSummaryTool
from ai.tools.position_trend import PositionTrendQuery, PositionTrendTool
from ai.tools.recent_trades import RecentTradesQuery, RecentTradesTool
from ai.tools.recent_transaction import RecentTransactionQuery, RecentTransactionTool
from ai.tools.user_position_summary import PositionSummaryQuery, UserPositionSummaryTool


@lru_cache(maxsize=1)
def _news_summary_service() -> NewsSummaryService:
    return NewsSummaryService()


@lru_cache(maxsize=1)
def _position_tool() -> UserPositionSummaryTool:
    return UserPositionSummaryTool()


@lru_cache(maxsize=1)
def _account_summary_tool() -> AccountSummaryTool:
    return AccountSummaryTool()


@lru_cache(maxsize=1)
def _account_trend_tool() -> AccountTrendTool:
    return AccountTrendTool()


@lru_cache(maxsize=1)
def _position_trend_tool() -> PositionTrendTool:
    return PositionTrendTool()


@lru_cache(maxsize=1)
def _recent_trades_tool() -> RecentTradesTool:
    return RecentTradesTool()


@lru_cache(maxsize=1)
def _recent_transaction_tool() -> RecentTransactionTool:
    return RecentTransactionTool()


@tool(args_schema=NewsSummaryQuery)
def news_summarize(**kwargs) -> str:
    """根据用户问题检索财经新闻并返回总结结果。"""
    return _news_summary_service().rag_summarize(NewsSummaryQuery(**kwargs))


@tool(args_schema=PositionSummaryQuery)
def get_user_position(**kwargs) -> str:
    """生成用户当前持仓的分析报告并直接返回最终文本。"""
    return _position_tool().get_position_summary(kwargs)


@tool(args_schema=AccountSummaryQuery)
def get_account_summary(**kwargs) -> dict:
    """返回用户当前所有账户的结构化摘要数据。"""
    return _account_summary_tool().get_account_summary(kwargs)


@tool(args_schema=AccountTrendQuery)
def get_account_trend(**kwargs) -> dict:
    """返回用户账户在指定时间段内的时间序列与趋势指标。"""
    return _account_trend_tool().get_account_trend(kwargs)


@tool(args_schema=PositionTrendQuery)
def get_position_trend(**kwargs) -> dict:
    """返回用户持仓在指定时间段内的时间序列与趋势指标。"""
    return _position_trend_tool().get_position_trend(kwargs)


@tool(args_schema=RecentTradesQuery)
def get_recent_trades(**kwargs) -> dict:
    """返回用户最近的投资交易记录。"""
    return _recent_trades_tool().get_recent_trades(kwargs)


@tool(args_schema=RecentTransactionQuery)
def get_recent_transaction(**kwargs) -> dict:
    """返回用户最近的账户交易记录，包括转账和手工记账。"""
    return _recent_transaction_tool().get_recent_transaction(kwargs)
