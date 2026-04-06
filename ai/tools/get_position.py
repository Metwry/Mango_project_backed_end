from ai.tools.user_position_summary import PositionSummaryQuery, UserPositionSummaryTool


class GetPositionTool:

    def __init__(self) -> None:
        self._tool = UserPositionSummaryTool()

    def get_position(self, request: dict) -> str:
        return self._tool.get_position_summary(request)
