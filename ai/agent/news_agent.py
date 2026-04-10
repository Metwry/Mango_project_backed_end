from __future__ import annotations

from typing import TypedDict

from langchain.agents import create_agent

from ai.agent.runtime_context import reset_agent_context, set_agent_context
from ai.config import get_prompt_text
from ai.llmmodels.model_factory import LLMModelFactory
from ai.tools.news.tools import get_current_time, news_summarize


class AgentContext(TypedDict):
    user_id: int
    session_id: int


class NewsAgent:
    def __init__(self):
        self.prompt_template = get_prompt_text("news_agent")
        self.agent = create_agent(
            model=LLMModelFactory.create_chat_model(task_name="news_agent"),
            system_prompt=self.prompt_template,
            tools=[get_current_time, news_summarize],
            context_schema=AgentContext,
        )

    def execute(
        self,
        messages: list[dict],
        context: AgentContext,
    ) -> str:
        token = set_agent_context(context)
        try:
            result = self.agent.invoke(
                {"messages": messages},
                context=context,
            )
            output_messages = result.get("messages", []) if isinstance(result, dict) else []
            last_message = output_messages[-1] if output_messages else None
            content = getattr(last_message, "content", "")
            return content if isinstance(content, str) else str(content or "")
        finally:
            reset_agent_context(token)
