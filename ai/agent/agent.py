
from typing import TypedDict

from django.utils import timezone

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from ai.agent.runtime_context import reset_agent_context, set_agent_context
from ai.config import get_prompt_text
from ai.llmmodels.model_factory import LLMModelFactory
from ai.agent.agent_tools import (
    get_account_trend,
    get_account_summary,
    get_position_trend,
    get_recent_trades,
    get_recent_transaction,
    get_user_position,
    news_summarize,
)


class AgentContext(TypedDict):
    user_id: int
    session_id: int


class ReactAgent:
    def __init__(self):
        self.agent = create_agent(
            model=LLMModelFactory.create_chat_model(task_name="news_answer"),
            system_prompt=get_prompt_text("system_agent"),
            tools=[
                news_summarize,
                get_user_position,
                get_account_summary,
                get_account_trend,
                get_position_trend,
                get_recent_trades,
                get_recent_transaction,
            ],
            context_schema=AgentContext,
        )

    def execute(self, messages: list[dict], context: AgentContext) -> str:
        token = set_agent_context(context)
        try:
            result = self.agent.invoke({"messages": self._inject_runtime_context(messages)}, context=context)
            return result["messages"][-1].content.strip()
        finally:
            reset_agent_context(token)

    def stream_execute(self, messages: list[dict], context: AgentContext):
        token = set_agent_context(context)
        try:
            for chunk in self.agent.stream(
                {"messages": self._inject_runtime_context(messages)},
                context=context,
                stream_mode="messages",
            ):
                if isinstance(chunk, tuple) and len(chunk) == 2:
                    message, metadata = chunk
                elif isinstance(chunk, dict) and chunk.get("type") == "messages":
                    data = chunk.get("data")
                    if not isinstance(data, tuple) or len(data) != 2:
                        continue
                    message, metadata = data
                else:
                    continue

                if not isinstance(message, AIMessageChunk):
                    continue
                if not isinstance(metadata, dict):
                    continue
                if metadata.get("langgraph_node") != "model":
                    continue

                content = message.content
                if isinstance(content, str):
                    if content:
                        yield content
                    continue

                if isinstance(content, list):
                    for item in content:
                        if isinstance(item, str):
                            if item:
                                yield item
                            continue
                        if isinstance(item, dict):
                            text = item.get("text")
                            if isinstance(text, str) and text:
                                yield text
        finally:
            reset_agent_context(token)

    def _inject_runtime_context(self, messages: list[dict]) -> list[dict]:
        now = timezone.localtime()
        runtime_message = {
            "role": "system",
            "content": (
                "当前系统时间锚点如下，请据此理解用户提到的“今天”“最近一周”“最近一个月”等相对时间，"
                "不要自行假设其他年份。\n"
                f"当前本地日期时间：{now.strftime('%Y-%m-%d %H:%M:%S %Z')}\n"
                f"当前本地日期：{now.strftime('%Y-%m-%d')}"
            ),
        }
        return [runtime_message, *messages]




if __name__ == "__main__":
    from django.contrib.auth import get_user_model
    from ai.services.chat_service import run_chat

    user = get_user_model().objects.get(id=3)

    result = run_chat(
        user=user,
        query="我的比特币现在怎么样",
    )
    print(result["session_id"])
    print(result["answer"])
