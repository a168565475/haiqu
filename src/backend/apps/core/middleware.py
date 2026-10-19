import uuid

from django.contrib.auth import logout as django_logout
from django.http import JsonResponse

from .auth import can_access_erp
from apps.wecom.selectors import waiting_for_role


class RequestIdMiddleware:
    header_name = "HTTP_X_REQUEST_ID"
    response_header_name = "X-Request-ID"

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.request_id = self._request_id(request.META.get(self.header_name))
        response = self.get_response(request)
        response[self.response_header_name] = request.request_id
        return response

    @staticmethod
    def _request_id(value):
        if value:
            try:
                return str(uuid.UUID(value))
            except (TypeError, ValueError, AttributeError):
                pass
        return str(uuid.uuid4())


class ErpSessionAccessMiddleware:
    session_endpoints = {
        "/api/auth/me/", "/api/auth/login/", "/api/auth/logout/", "/api/health/",
        "/api/auth/wecom/start/", "/api/auth/wecom/callback/",
    }

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        if request.user.is_authenticated and not can_access_erp(request.user):
            django_logout(request)
        elif (
            request.user.is_authenticated
            and request.path.startswith(("/api/", "/admin/"))
            and request.path not in self.session_endpoints
            and waiting_for_role(request.user)
        ):
            # 保留已验证的会话，让员工能查询授权状态或退出；业务访问仍由后端拦截。
            return JsonResponse({"error": {
                "code": "WECOM_ROLE_REQUIRED",
                "message": "等待管理员分配角色",
                "field_errors": {},
                "request_id": getattr(request, "request_id", None),
            }}, status=403)
        return self.get_response(request)
