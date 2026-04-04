from langchain_core.tools import tool
from langgraph.prebuilt.tool_node import ToolRuntime

from ai.rag.newsSummaryService import NewsSummaryQuery, NewsSummaryService
from ai.tools.get_position import GetPositionTool, PositionSummaryQuery

newsSummaryService = NewsSummaryService()
positionTool = GetPositionTool()


@tool(args_schema=NewsSummaryQuery)
def news_summarize(**kwargs) -> str:
    """根据用户问题检索财经新闻并返回总结结果。"""
    return newsSummaryService.rag_summarize(NewsSummaryQuery(**kwargs))


@tool(args_schema=PositionSummaryQuery)
def get_user_position(runtime: ToolRuntime, **kwargs) -> str:
    """生成用户当前持仓的分析报告并直接返回最终文本。"""
    return positionTool.get_position({**kwargs, "context": runtime.context or {}})


def get_market_price(**kwargs) -> list:
    """查找市场数据"""
    pass


def get_snapshot(**kwargs) -> dict:
    """查找用户的历史走势"""
    pass


def add_manual_transaction(**kwargs) -> dict:
    """帮用户记录交易"""
