from __future__ import annotations

import os
from pathlib import Path

import django


def main() -> None:
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mango_project.settings")
    django.setup()

    from ai.agent.trading_agent.graph import TradingWorkflow

    workflow = TradingWorkflow()
    png_bytes = workflow.graph.get_graph().draw_mermaid_png()
    output_path = Path(__file__).resolve().with_name("trading_workflow.png")
    output_path.write_bytes(png_bytes)
    print(output_path)


if __name__ == "__main__":
    main()
