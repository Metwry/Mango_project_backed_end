from __future__ import annotations

__all__ = ["TradingWorkflow"]


def __getattr__(name: str):
    if name == "TradingWorkflow":
        from .graph import TradingWorkflow

        return TradingWorkflow
    raise AttributeError(name)
