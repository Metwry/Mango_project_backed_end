from __future__ import annotations

from .state import TradingGraphState


def route_after_agent(state: TradingGraphState) -> str:
    if state.get("has_tool_calls"):
        return "tool_node"
    payload = state.get("agent_result") or {}
    mapping = {
        "ASK_CLARIFY": "end",
        "PREVIEW": "preview_trade",
        "EXECUTE": "execute_trade",
        "CANCEL": "cancel_trade",
        "INVALID": "end",
    }
    return mapping.get(str(payload.get("next_action") or "").upper(), "end")
