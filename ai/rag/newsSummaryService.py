from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field
from langchain_core.output_parsers import StrOutputParser
from langchain_core.prompts import ChatPromptTemplate

from ai.config import get_prompt_text
from ai.llmmodels import LLMModelFactory
from news.service.news_search import NewsSearchResult, NewsSearchService



class NewsSummaryQuery(BaseModel):
    query: str = Field(description="用户的问题")
    response_mode: str = Field(description="回答模式: overview 或 detail")
    top_k: int | None = Field(default=None, description="检索条数")
    published_from: datetime | None = Field(default=None, description="开始时间")
    published_to: datetime | None = Field(default=None, description="结束时间")


class NewsSummaryService:
    TASK_NAME = "news_answer"
    EMPTY_RESULT_TEXT = "未检索到足够相关的财经新闻，暂时无法给出可靠回答。"

    def __init__(self) -> None:
        self.search_service = NewsSearchService()
        self.prompt_text = get_prompt_text(self.TASK_NAME)
        self.prompt_template = ChatPromptTemplate.from_template(self.prompt_text)
        self.model = LLMModelFactory.create_chat_model(task_name=self.TASK_NAME)
        self.chain = self._init_chain()

    def _init_chain(self):
        return self.prompt_template | self.model | StrOutputParser()

    def rag_summarize(self, request: NewsSummaryQuery) -> str:
        result: NewsSearchResult = self.search_service.search(
            query=request.query,
            response_mode=request.response_mode,
            top_k=request.top_k,
            published_from=request.published_from,
            published_to=request.published_to,
        )
        if result.hit_count == 0:
            return self.EMPTY_RESULT_TEXT

        return self.chain.invoke(
            {
                "query": request.query,
                "response_mode": request.response_mode,
                "context": result.context,
            }
        ).strip()


if __name__ == '__main__':
    rag = NewsSummaryService()
    print(rag.rag_summarize(NewsSummaryQuery(query="最近有什么新闻", response_mode="overview")))
