from datetime import datetime
from langchain_core.tools import tool

from ai.agent.rag.newsSummaryService import NewsSummaryQuery, NewsSummaryService

newsSummaryService = NewsSummaryService()

@tool(args_schema=NewsSummaryQuery)
def news_summarize(**kwargs) -> str:
    """根据用户问题检索财经新闻并返回总结结果。"""
    return newsSummaryService.rag_summarize(NewsSummaryQuery(**kwargs))
