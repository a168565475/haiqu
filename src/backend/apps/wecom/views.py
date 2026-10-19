from django.http import HttpResponseRedirect
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from django.views.decorators.http import require_GET
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_control.permissions import CanManageAccess
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import HasActiveEmployee
from . import selectors, services
from .client import WeComError
from .credentials import CredentialError
from .middleware import WeComExceptionReporterFilter, take_callback_parameters
from .serializers import (
    AuditListSerializer, BindingListSerializer, BindingQuerySerializer, BindingResponseSerializer,
    BindingWriteSerializer, ConfigResponseSerializer, ConfigWriteSerializer,
    EmployeeListSerializer, EmployeeQuerySerializer, PageQuerySerializer,
)


IF_MATCH = OpenApiParameter("If-Match", str, OpenApiParameter.HEADER, required=True)


class WeComUnavailable(APIException):
    status_code = 503
    default_detail = "企业微信模块尚未执行已审阅的数据库迁移。"
    default_code = "wecom_unavailable"
    api_error_code = "WECOM_UNAVAILABLE"


class WeComUpstreamFailure(APIException):
    status_code = 502
    default_detail = "企业微信接口暂不可用，请检查配置或稍后重试。"
    api_error_code = "WECOM_UPSTREAM_ERROR"


@method_decorator(sensitive_post_parameters("secret", "callback_token", "callback_aes_key"), name="dispatch")
class ManagementView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanManageAccess]

    def initial(self, request, *args, **kwargs):
        request._request.exception_reporter_filter = WeComExceptionReporterFilter()
        super().initial(request, *args, **kwargs)
        if not selectors.schema_is_ready():
            raise WeComUnavailable()

    def handle_exception(self, exc):
        if isinstance(exc, CredentialError):
            exc = Conflict(CredentialError.message)
        elif isinstance(exc, services.OAuthFailure):
            exc = Conflict("企业微信成员无效、不在应用可见范围内，或所选员工账号不可用。")
        elif isinstance(exc, WeComError):
            exc = WeComUpstreamFailure()
        return super().handle_exception(exc)


@sensitive_variables()
def config_response(config):
    payload = ConfigResponseSerializer({"data": selectors.config_payload(config)}).data
    return Response(payload, headers={"ETag": selectors.config_etag(config)})


class ConfigView(ManagementView):
    @extend_schema(responses=ConfigResponseSerializer)
    @sensitive_variables()
    def get(self, request):
        return config_response(selectors.get_config())

    @extend_schema(request=ConfigWriteSerializer, responses=ConfigResponseSerializer, parameters=[IF_MATCH])
    @sensitive_variables()
    def patch(self, request):
        serializer = ConfigWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return config_response(services.update_config(request, serializer.validated_data))


class ConfigCheckView(ManagementView):
    @extend_schema(request=None, responses=ConfigResponseSerializer, parameters=[IF_MATCH])
    @sensitive_variables()
    def post(self, request):
        return config_response(services.check_connection(request))


def paginated_response(queryset, parameters, payload, serializer_class):
    page, page_size = parameters["page"], parameters["page_size"]
    start = (page - 1) * page_size
    result = {"data": [payload(row) for row in queryset[start:start + page_size]], "count": queryset.count(),
              "page": page, "page_size": page_size}
    return Response(serializer_class(result).data)


class BindingsView(ManagementView):
    @extend_schema(parameters=[BindingQuerySerializer], responses=BindingListSerializer)
    def get(self, request):
        query = BindingQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        values = query.validated_data
        queryset = selectors.bindings_queryset(values["search"], values["status"])
        return paginated_response(queryset, values, selectors.binding_payload, BindingListSerializer)

    @extend_schema(request=BindingWriteSerializer, responses={201: BindingResponseSerializer}, parameters=[IF_MATCH])
    def post(self, request):
        serializer = BindingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        binding = services.bind_employee(request, serializer.validated_data)
        return Response(BindingResponseSerializer({"data": selectors.binding_payload(binding)}).data, status=201)


class EmployeesView(ManagementView):
    @extend_schema(parameters=[EmployeeQuerySerializer], responses=EmployeeListSerializer)
    def get(self, request):
        query = EmployeeQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(EmployeeListSerializer({"data": selectors.employee_options(query.validated_data["search"])}).data)


class AuditsView(ManagementView):
    @extend_schema(parameters=[PageQuerySerializer], responses=AuditListSerializer)
    def get(self, request):
        query = PageQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return paginated_response(selectors.audits_queryset(), query.validated_data, selectors.audit_payload, AuditListSerializer)


def oauth_error(reason):
    # reason 仅来自内部枚举，不拼接第三方错误、code、凭据或用户输入。
    public_codes = {"INVALID_STATE": "STATE_INVALID", "CONFIG_UNAVAILABLE": "CONFIGURATION_ERROR",
                    "CONFIGURATION_ERROR": "CONFIGURATION_ERROR", "ACCOUNT_MISMATCH": "IDENTITY_MISMATCH",
                    "MEMBER_REJECTED": "MEMBER_REJECTED", "UPSTREAM_UNAVAILABLE": "UPSTREAM_UNAVAILABLE"}
    return HttpResponseRedirect("/auth/wecom-error?reason=" + public_codes.get(reason, "LOGIN_FAILED"))


@never_cache
@require_GET
@sensitive_variables()
def oauth_start(request):
    request.exception_reporter_filter = WeComExceptionReporterFilter()
    if not selectors.schema_is_ready():
        return oauth_error("CONFIG_UNAVAILABLE")
    if request.GET:
        return oauth_error("INVALID_REQUEST")
    config = selectors.get_config()
    if config._state.adding or not config.enabled or not selectors.configuration_complete(config):
        return oauth_error("CONFIG_UNAVAILABLE")
    return HttpResponseRedirect(services.oauth_url(request, config))


@never_cache
@require_GET
@sensitive_variables()
def oauth_callback(request):
    state, code = take_callback_parameters(request)
    if not selectors.schema_is_ready():
        return oauth_error("CONFIG_UNAVAILABLE")
    try:
        destination = services.oauth_login(request, state, code)
    except services.OAuthFailure as exc:
        services.audit_login_failure(request, exc.code)
        return oauth_error(exc.code)
    except CredentialError:
        services.audit_login_failure(request, "CONFIG_UNAVAILABLE")
        return oauth_error("CONFIG_UNAVAILABLE")
    except WeComError as exc:
        reason = exc.code if exc.code in {"MEMBER_REJECTED", "CONFIGURATION_ERROR"} else "UPSTREAM_UNAVAILABLE"
        services.audit_login_failure(request, reason)
        return oauth_error(reason)
    return HttpResponseRedirect(destination)
