from __future__ import annotations

import os
from pathlib import Path
import sys

import django


def main() -> None:
    project_root = Path(__file__).resolve().parents[2]
    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "mango_project.settings")
    django.setup()

    from ai.agent.graph import GlobalAgentWorkflow
    from ai.agent.trading.graph import TradingWorkflow

    global_workflow = GlobalAgentWorkflow()
    global_png = global_workflow.graph.get_graph().draw_mermaid_png()
    global_output_path = Path(__file__).resolve().with_name("global_agent_workflow.png")
    global_output_path.write_bytes(global_png)
    print(global_output_path)

    trading_workflow = TradingWorkflow()
    trading_png = trading_workflow.graph.get_graph().draw_mermaid_png()
    trading_output_path = Path(__file__).resolve().with_name("trading_agent_workflow.png")
    trading_output_path.write_bytes(trading_png)
    print(trading_output_path)


if __name__ == "__main__":
    main()
