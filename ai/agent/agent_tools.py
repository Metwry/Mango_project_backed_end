from langchain_core.tools import tool
from ai.rag.newsSummaryService import NewsSummaryQuery, NewsSummaryService
from ai.tools.account_trend import AccountTrendQuery, AccountTrendTool
from ai.tools.account_summary import AccountSummaryQuery, AccountSummaryTool
from ai.tools.position_trend import PositionTrendQuery, PositionTrendTool
from ai.tools.recent_trades import RecentTradesQuery, RecentTradesTool
from ai.tools.recent_transaction import RecentTransactionQuery, RecentTransactionTool
from ai.tools.user_position_summary import PositionSummaryQuery, UserPositionSummaryTool

newsSummaryService = NewsSummaryService()
positionTool = UserPositionSummaryTool()
accountSummaryTool = AccountSummaryTool()
accountTrendTool = AccountTrendTool()
positionTrendTool = PositionTrendTool()
recentTradesTool = RecentTradesTool()
recentTransactionTool = RecentTransactionTool()


@tool(args_schema=NewsSummaryQuery)
def news_summarize(**kwargs) -> str:
    """根据用户问题检索财经新闻并返回总结结果。"""
    return newsSummaryService.rag_summarize(NewsSummaryQuery(**kwargs))


@tool(args_schema=PositionSummaryQuery)
def get_user_position(**kwargs) -> str:
    """生成用户当前持仓的分析报告并直接返回最终文本。"""
    return positionTool.get_position_summary(kwargs)


@tool(args_schema=AccountSummaryQuery)
def get_account_summary(**kwargs) -> dict:
    """返回用户当前所有账户的结构化摘要数据。"""
    return accountSummaryTool.get_account_summary(kwargs)


@tool(args_schema=AccountTrendQuery)
def get_account_trend(**kwargs) -> dict:
    """返回用户账户在指定时间段内的时间序列与趋势指标。"""
    return accountTrendTool.get_account_trend(kwargs)


@tool(args_schema=PositionTrendQuery)
def get_position_trend(**kwargs) -> dict:
    """返回用户持仓在指定时间段内的时间序列与趋势指标。"""
    return positionTrendTool.get_position_trend(kwargs)


@tool(args_schema=RecentTradesQuery)
def get_recent_trades(**kwargs) -> dict:
    """返回用户最近的投资交易记录。"""
    return recentTradesTool.get_recent_trades(kwargs)


@tool(args_schema=RecentTransactionQuery)
def get_recent_transaction(**kwargs) -> dict:
    """返回用户最近的账户交易记录，包括转账和手工记账。"""
    return recentTransactionTool.get_recent_transaction(kwargs)
