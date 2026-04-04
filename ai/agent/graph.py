from  typing import  List,TypedDict

from langchain_classic.chains.question_answering.map_reduce_prompt import messages
from  langgraph.graph import StateGraph



class AgentState(TypedDict):
    message: str
    name: str
    values:list[int]


def greeting_node(state: AgentState) -> AgentState:
    """greeting message"""
    state["message"] = "Hi" + state["name"]
    return state

def praise_node(state:AgentState) -> AgentState:
    """praise person"""
    state["message"] = state["name"] + "you are good"
    return state


graph = StateGraph(AgentState)

graph.add_node("greeter",greeting_node)
graph.add_node("praise",praise_node)
graph.set_entry_point("greeter")
graph.add_edge("greeter","praise")
graph.set_finish_point("praise")

app = graph.compile()

result = app.invoke({
    "name":'WRY'
})

print(result["message"])