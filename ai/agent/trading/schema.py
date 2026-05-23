from __future__ import annotations

import json
from typing import Literal

from langchain_core.messages import BaseMessage, HumanMessage, SystemMessage
from langchain_core.tools import tool
from pydantic import BaseModel, Field

from ai.config import get_prompt_path


TRADING_SYSTEM_PROMPT = get_prompt_path("trading.txt").read_text(encoding="utf-8").strip()
DECISION_TOOL_NAME = "submit_trade_decision"


class TradeDraft(BaseModel):
    side: Literal["BUY", "SELL"] | None = None
    instrument_id: int | None = None
    cash_account_id: int | None = None
    quantity: str | None = None
    price: str | None = None

    @classmethod
    def from_payload(cls, payload: dict | None) -> "TradeDraft":
        if not isinstance(payload, dict):
            return cls()
        data: dict[str, object] = {}
        side = payload.get("side")
        if isinstance(side, str):
            upper = side.upper()
            if upper in {"BUY", "SELL"}:
                data["side"] = upper
        for key in ("instrument_id", "cash_account_id"):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                data[key] = int(value)
        for key in ("quantity", "price"):
            value = payload.get(key)
            if value not in (None, "", [], {}):
                data[key] = str(value)
        return cls(**data)

    def to_payload(self) -> dict:
        payload: dict[str, object] = {}
        for key in ("side", "instrument_id", "cash_account_id", "quantity", "price"):
            value = getattr(self, key)
            if value is not None:
                payload[key] = value
        return payload

    def merge(self, other: "TradeDraft") -> "TradeDraft":
        merged = self.to_payload()
        merged.update(other.to_payload())
        return TradeDraft.from_payload(merged)

    def is_complete(self) -> bool:
        return all(
            getattr(self, key) is not None
            for key in ("side", "instrument_id", "cash_account_id", "quantity", "price")
        )

    def has_changes(self, other: "TradeDraft") -> bool:
        return any(getattr(self, key) != getattr(other, key) for key in self.__class__.model_fields)


class AgentDecisionInput(BaseModel):
    next_action: Literal["ASK_CLARIFY", "PREVIEW", "EXECUTE", "CANCEL", "INVALID"]
    message: str = Field(min_length=1)
    side: Literal["BUY", "SELL"] | None = None
    instrument_id: int | None = None
    cash_account_id: int | None = None
    quantity: str | None = None
    price: str | None = None


class AgentDecision(BaseModel):
    next_action: Literal["ASK_CLARIFY", "PREVIEW", "EXECUTE", "CANCEL", "INVALID"]
    message: str
    draft: TradeDraft = Field(default_factory=TradeDraft)

    @classmethod
    def from_tool_args(cls, args: dict) -> "AgentDecision":
        payload = AgentDecisionInput.model_validate(args)
        return cls(
            next_action=payload.next_action,
            message=payload.message.strip(),
            draft=TradeDraft(
                side=payload.side,
                instrument_id=payload.instrument_id,
                cash_account_id=payload.cash_account_id,
                quantity=payload.quantity,
                price=payload.price,
            ),
        )


@tool(args_schema=AgentDecisionInput)
def submit_trade_decision(
    next_action: str,
    message: str,
    side: str | None = None,
    instrument_id: int | None = None,
    cash_account_id: int | None = None,
    quantity: str | None = None,
    price: str | None = None,
) -> str:
    """在完成分析后提交最终交易决策。不要在同一轮同时调用它和其他交易工具。"""
    return ""


def build_agent_messages(
    *,
    draft: TradeDraft,
    draft_status: str,
    current_messages: list[BaseMessage],
    time_tool_called: bool,
) -> list[BaseMessage]:
    current_user_message = ""
    for message in reversed(current_messages):
        if isinstance(message, HumanMessage):
            current_user_message = str(message.content or "")
            break
    context_payload = {
        "draft": draft.to_payload(),
        "draft_status": draft_status,
        "current_user_message": current_user_message,
        "time_tool_called": time_tool_called,
    }
    return [
        SystemMessage(content=TRADING_SYSTEM_PROMPT),
        SystemMessage(
            content=(
                "你是交易工作流中的决策节点。"
                "如果需要更多信息，请调用交易工具。"
                "在单次用户请求中，get_current_time 最多只能调用一次；"
                "如果 context_payload.time_tool_called 为 true，就不要再次调用 get_current_time。"
                "解析标的前，先从用户原句提取核心标的词或代码；"
                "不要把买卖动作、数量、市场描述整句原样传给 resolve_trade_instrument。"
                "如果 resolve_trade_instrument 返回多个 candidates，且其中只有一个是普通公司/正股、其余是 ETF 或杠杆反向品，"
                "而用户又没有明确要求 ETF/杠杆/做多做空，则直接选择普通公司/正股。"
                "如果已经可以决定下一步，请只调用 submit_trade_decision。"
                "不要输出自然语言，不要在同一轮同时调用 submit_trade_decision 和其他工具。\n"
                f"{json.dumps(context_payload, ensure_ascii=False)}"
            )
        ),
        *current_messages,
    ]


def derive_draft_status(
    *,
    previous_draft: TradeDraft,
    next_draft: TradeDraft,
    previous_status: str,
) -> str:
    if not next_draft.to_payload():
        return "EMPTY"
    if previous_draft.has_changes(next_draft):
        return "DRAFT_EDITING"
    return previous_status


def render_response(*, event: str, payload: dict) -> str:
    message = payload.get("message")
    if isinstance(message, str) and message.strip() and event != "PREVIEW_READY":
        return message.strip()
    if event == "TOOL_REQUESTED":
        return "正在查询交易信息。"
    if event == "TOOL_LIMIT_REACHED":
        return "工具调用次数已达上限，请调整交易请求后重试。"
    if event == "PREVIEW_FAILED":
        return str(payload.get("message") or "交易预览失败。")
    if event == "PREVIEW_READY":
        preview = payload["preview"]
        if preview.get("can_execute"):
            status_text = "当前条件满足，可以继续执行。回复“确认”执行，回复“取消”放弃。"
        elif str(preview.get("side") or "").upper() == "BUY":
            status_text = "当前条件暂不满足：账户余额不足。"
        else:
            status_text = "当前条件暂不满足：持仓数量不足。"
        return (
            f"交易预览：{preview['side']} {preview['instrument_name']}({preview['instrument_symbol']}) "
            f"{preview['quantity']}，使用 {preview['cash_account_name']}，价格 {preview['price']}，"
            f"预计金额 {preview['estimated_amount']}。{status_text}"
        )
    if event == "CANCELLED":
        return "本次交易已取消。"
    return "当前交易请求处理完成。"
