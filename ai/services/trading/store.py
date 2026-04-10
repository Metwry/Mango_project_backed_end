from __future__ import annotations

from django.core.cache import cache


TRADE_DRAFT_TIMEOUT_SECONDS = 15 * 60


def _trade_draft_key(*, user_id: int, session_id: int) -> str:
    return f"agent:workflow:trading:{user_id}:{session_id}"


def load_trade_draft(*, user_id: int, session_id: int) -> dict | None:
    payload = cache.get(_trade_draft_key(user_id=user_id, session_id=session_id))
    return payload if isinstance(payload, dict) else None


def save_trade_draft(*, user_id: int, session_id: int, draft: dict) -> None:
    cache.set(
        _trade_draft_key(user_id=user_id, session_id=session_id),
        draft,
        timeout=TRADE_DRAFT_TIMEOUT_SECONDS,
    )


def clear_trade_draft(*, user_id: int, session_id: int) -> None:
    cache.delete(_trade_draft_key(user_id=user_id, session_id=session_id))


def has_active_trade_draft(*, user_id: int, session_id: int) -> bool:
    return load_trade_draft(user_id=user_id, session_id=session_id) is not None


def build_trade_workflow_payload(*, draft: dict | None, draft_status: str) -> dict:
    return {
        "draft": dict(draft or {}),
        "draft_status": draft_status,
    }
