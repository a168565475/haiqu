from django.http import QueryDict
from django.views.debug import SafeExceptionReporterFilter
from django.views.decorators.debug import sensitive_variables


class WeComExceptionReporterFilter(SafeExceptionReporterFilter):
    def is_active(self, request):
        # 本模块含凭据；开发模式也必须执行敏感变量过滤。
        return True


@sensitive_variables()
def protect_callback_request(request):
    request.exception_reporter_filter = WeComExceptionReporterFilter()
    if hasattr(request, "_wecom_oauth_parameters"):
        return
    query_string = request.META.get("QUERY_STRING", "")
    # 先清理错误报告可见的原始请求，再解析；解析异常同样不暴露查询参数。
    request.GET = QueryDict("")
    for field in ("QUERY_STRING", "RAW_URI", "REQUEST_URI"):
        if field in request.META:
            request.META[field] = "" if field == "QUERY_STRING" else request.path
    parameters = QueryDict(query_string, encoding=request.encoding)
    request._wecom_oauth_parameters = (parameters.get("state", ""), parameters.get("code", ""))


@sensitive_variables()
def take_callback_parameters(request):
    # 直接调用视图时仍有保护；常规请求已由第一层中间件保存参数。
    protect_callback_request(request)
    return request.__dict__.pop("_wecom_oauth_parameters")


class WeComOAuthSensitiveMiddleware:
    """必须位于会话和认证中间件前，以覆盖它们的数据库异常。"""

    def __init__(self, get_response):
        self.get_response = get_response

    @sensitive_variables()
    def __call__(self, request):
        if request.path.rstrip("/") != "/api/auth/wecom/callback":
            return self.get_response(request)
        try:
            protect_callback_request(request)
            return self.get_response(request)
        finally:
            request.__dict__.pop("_wecom_oauth_parameters", None)
