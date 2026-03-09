from rest_framework.views import exception_handler


def _first_error_message(detail) -> str:
    if isinstance(detail, dict):
        if "message" in detail and detail["message"]:
            return str(detail["message"])
        if "detail" in detail and detail["detail"]:
            return str(detail["detail"])
        first = next(iter(detail.values()), None)
        return _first_error_message(first)
    if isinstance(detail, list):
        if not detail:
            return "请求失败"
        return _first_error_message(detail[0])
    if detail is None:
        return "请求失败"
    return str(detail)


def custom_exception_handler(exc, context):
    response = exception_handler(exc, context)
    if response is None:
        return None

    data = response.data
    if isinstance(data, dict):
        if "message" in data:
            data["message"] = _first_error_message(data["message"])
        else:
            data["message"] = _first_error_message(data)
        # Frontend only consumes `message`; remove duplicate DRF `detail`.
        data.pop("detail", None)
    elif isinstance(data, list):
        response.data = {
            "errors": data,
            "message": _first_error_message(data),
        }

    return response
