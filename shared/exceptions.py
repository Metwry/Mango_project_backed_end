from rest_framework import status
from rest_framework.exceptions import APIException


class BusinessConflictError(APIException):
    """表示业务规则冲突的 409 异常。"""

    status_code = status.HTTP_409_CONFLICT
    default_detail = "业务冲突"
    default_code = "business_conflict"


class LoginFailedError(APIException):
    """表示登录失败的 401 异常。"""

    status_code = status.HTTP_401_UNAUTHORIZED
    default_detail = "邮箱/用户名或密码错误"
    default_code = "login_failed"
