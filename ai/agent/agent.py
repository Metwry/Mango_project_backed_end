
from langchain.agents import create_agent
from ai.config import get_prompt_text
from ai.llmmodels.model_factory import LLMModelFactory
from ai.agent.agent_tools import news_summarize


class ReactAgent:
    def __init__(self):
        self.agent = create_agent(
            model=LLMModelFactory.create_chat_model(task_name="news_answer"),
            system_prompt=get_prompt_text("system_agent"),
            tools=[news_summarize],
            middleware=[],
        )

    def execute(self, query: str) -> str:
        input_dict = {
            "messages": [
                {"role": "user", "content": query},
            ]
        }
        result = self.agent.invoke(input_dict)
        return result["messages"][-1].content.strip()


if __name__ == '__main__':
    agent = ReactAgent()
    for chunk in agent.execute("最近有什么新闻吗"):
        print(chunk, end ="",flush=True)
