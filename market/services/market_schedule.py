from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

from .market_utils import normalize_market_code, should_fetch_market, should_pull_market_tick


@dataclass(frozen=True)
class GuardDecision:
    market: str
    should_pull: bool
    reason: str
    session: str = "regular"


# 根据市场日历和拉取节奏判断当前是否应抓取行情。
def market_guard_decision(market: str, now_utc: datetime | None = None) -> GuardDecision:
    now = now_utc or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    market_code = normalize_market_code(market)

    if not should_fetch_market(market_code, now):
        return GuardDecision(market=market_code, should_pull=False, reason="outside_session", session="none")
    if should_pull_market_tick(market_code, now):
        return GuardDecision(market=market_code, should_pull=True, reason="due")
    return GuardDecision(market=market_code, should_pull=False, reason="not_due")


# 批量计算哪些市场当前需要拉取行情。
def resolve_due_markets(markets: Iterable[str], now_utc: datetime | None = None) -> tuple[set[str], dict[str, GuardDecision]]:
    due: set[str] = set()
    decisions: dict[str, GuardDecision] = {}
    for market in {normalize_market_code(x) for x in markets if normalize_market_code(x)}:
        decision = market_guard_decision(market, now_utc=now_utc)
        decisions[market] = decision
        if decision.should_pull:
            due.add(market)
    return due, decisions
