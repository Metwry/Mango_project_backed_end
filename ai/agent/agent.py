
from typing import TypedDict

from langchain.agents import create_agent
from langchain_core.messages import AIMessageChunk
from ai.config import get_prompt_text
from ai.llmmodels.model_factory import LLMModelFactory
from ai.agent.agent_tools import get_user_position, news_summarize


class AgentContext(TypedDict):
    user_id: int
    session_id: int


class ReactAgent:
    def __init__(self):
        self.agent = create_agent(
            model=LLMModelFactory.create_chat_model(task_name="news_answer"),
            system_prompt=get_prompt_text("system_agent"),
            tools=[news_summarize, get_user_position],
            middleware=[],
            context_schema=AgentContext,
        )

    def execute(self, messages: list[dict], context: AgentContext) -> str:
        result = self.agent.invoke({"messages": messages}, context=context)
        return result["messages"][-1].content.strip()

    def stream_execute(self, messages: list[dict], context: AgentContext):
        for chunk in self.agent.stream(
            {"messages": messages},
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
