from rest_framework import status
from rest_framework.exceptions import (
    APIException,
    AuthenticationFailed,
    ErrorDetail,
    NotAuthenticated,
    NotFound,
    PermissionDenied,
    Throttled,
    ValidationError,
)
from rest_framework.views import exception_handler


class Conflict(APIException):
    status_code = status.HTTP_409_CONFLICT
    default_detail = "请求与当前数据状态冲突。"
    default_code = "conflict"


def _plain_value(value):
    if isinstance(value, dict):
        return {key: _plain_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_plain_value(item) for item in value]
    if isinstance(value, ErrorDetail):
        return str(value)
    return value


def _first_message(value):
    if isinstance(value, dict):
        for item in value.values():
            message = _first_message(item)
            if message:
                return message
    elif isinstance(value, (list, tuple)):
        for item in value:
            message = _first_message(item)
            if message:
                return message
    elif value:
        return str(value)
    return "请求处理失败"


def _error_code(exc, response):
    if isinstance(exc, ValidationError):
        return "VALIDATION_ERROR"
    if isinstance(exc, (NotAuthenticated, AuthenticationFailed)):
        return "AUTHENTICATION_REQUIRED"
    if isinstance(exc, PermissionDenied):
        return "PERMISSION_DENIED"
    if isinstance(exc, NotFound):
        return "NOT_FOUND"
    if isinstance(exc, Throttled):
        return "TOO_MANY_REQUESTS"
    if response.status_code == status.HTTP_409_CONFLICT:
        return "CONFLICT"
    if response.status_code == status.HTTP_412_PRECONDITION_FAILED:
        return "PRECONDITION_FAILED"
    if response.status_code == status.HTTP_428_PRECONDITION_REQUIRED:
        return "PRECONDITION_REQUIRED"
    return "REQUEST_FAILED"


def api_exception_handler(exc, context):
    response = exception_handler(exc, context)
    request = context.get("request")

    if request is None or not request.path.startswith("/api/v1/"):
        return response
    if response is None:
        return None

    details = _plain_value(response.data)
    field_errors = details if isinstance(exc, ValidationError) and isinstance(details, dict) else {}
    response.data = {
        "error": {
            "code": _error_code(exc, response),
            "message": _first_message(details),
            "field_errors": field_errors,
            "request_id": getattr(request, "request_id", None),
        }
    }
    return response
