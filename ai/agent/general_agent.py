from __future__ import annotations

from typing import TypedDict

from langchain.agents import create_agent

from ai.agent.runtime_context import reset_agent_context, set_agent_context
from ai.tools.general.tools import (
    get_account_summary,
    get_account_trend,
    get_current_time,
    get_position_trend,
    get_recent_trades,
    get_recent_transaction,
    get_user_position,
)
from ai.config import get_prompt_text
from ai.llmmodels.model_factory import LLMModelFactory


class AgentContext(TypedDict):
    user_id: int
    session_id: int


class GeneralAgent:
    def __init__(self):
        self.prompt_template = get_prompt_text("general_agent")
        self.agent = create_agent(
            model=LLMModelFactory.create_chat_model(task_name="general_agent"),
            system_prompt=self.prompt_template,
            tools=[
                get_current_time,
                get_user_position,
                get_account_summary,
                get_account_trend,
                get_position_trend,
                get_recent_trades,
                get_recent_transaction,
            ],
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
