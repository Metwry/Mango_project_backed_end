from __future__ import annotations

from contextvars import ContextVar, Token


_AGENT_CONTEXT: ContextVar[dict | None] = ContextVar("_AGENT_CONTEXT", default=None)


def set_agent_context(context: dict | None) -> Token:
    return _AGENT_CONTEXT.set(context or {})


def reset_agent_context(token: Token) -> None:
    _AGENT_CONTEXT.reset(token)


def get_agent_context() -> dict:
    return _AGENT_CONTEXT.get() or {}
