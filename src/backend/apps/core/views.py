import redis
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login as django_login, logout as django_logout
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, transaction
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .auth import can_access_erp
from .login_records import record_successful_login
from .serializers import (
    AuthenticationStateSerializer, HealthResponseSerializer, LoginSerializer,
    ReturnAdminSerializer, SwitchAccountSerializer, SwitchTargetQuerySerializer,
    SwitchTargetsResponseSerializer,
)
from . import identity_switch_services as identity
from .identity_switch_selectors import switch_target_list


def user_payload(user):
    from types import SimpleNamespace

    from apps.access_control import module_policy, sales_policy
    from apps.wecom.selectors import waiting_for_role

    employee_payload = None
    try:
        employee = user.employee_profile
    except ObjectDoesNotExist:
        employee = None

    if employee is not None:
        employee_payload = {
            "id": employee.pk,
            "employee_code": employee.employee_code,
            "display_name": employee.display_name,
            "status": employee.status,
        }

    if user.is_superuser or user.has_perm("customers.view_all_customer"):
        data_scope = "ALL"
    elif employee is not None:
        data_scope = "ASSIGNED_AND_GRANTED"
    else:
        data_scope = "NONE"

    payload = {
        "id": user.pk,
        "username": user.get_username(),
        "display_name": user.get_full_name() or user.get_username(),
        "is_superuser": user.is_superuser,
        "employee": employee_payload,
        "permissions": sorted(user.get_all_permissions()),
        "data_scope": data_scope,
    }
    # 身份输出和兼容权限共用本次计算；下次调用仍重新检查授权。
    request = SimpleNamespace(user=user, employee=employee)
    if settings.ACCESS_MANAGEMENT_ENABLED:
        payload["effective_access"] = sales_policy.access_for(request)
    payload["sales_access_enabled"] = sales_policy.enabled()
    payload['module_access_enabled'] = module_policy.enabled()
    if module_policy.enabled():
        payload['permissions'] = sorted(set(payload['permissions']) | {
            code for code in module_policy.LEGACY_ALIASES if module_policy.has_permission(request, code)})
    if sales_policy.enabled():
        payload["permissions"] = sorted(set(payload["permissions"]) | {code for code in sales_policy.LEGACY_ACTION_PERMISSIONS if sales_policy.has_permission(request, code)})
    payload["waiting_for_role"] = waiting_for_role(user)
    if payload["waiting_for_role"]:
        payload["permissions"] = []
        payload["data_scope"] = "NONE"
    return payload


@extend_schema(
    request=LoginSerializer,
    responses={
        200: AuthenticationStateSerializer,
        400: OpenApiResponse(description="用户名、密码或请求字段错误"),
    },
)
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def auth_login(request):
    serializer = LoginSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)

    user = authenticate(
        request=request,
        username=serializer.validated_data["username"],
        password=serializer.validated_data["password"],
    )
    if user is None or not can_access_erp(user):
        return Response(
            {"detail": "用户名或密码错误"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    # Serialize session creation with account suspension; suspension deletes all
    # existing DB sessions while holding this same user lock.
    with transaction.atomic():
        from apps.organizations.models import Employee
        # 登录审计会引用员工，沿用员工→账号锁顺序，避免与删除/停用互相等待。
        Employee.objects.select_for_update(no_key=True).filter(user_id=user.pk).first()
        backend = user.backend
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not can_access_erp(user) or not user.check_password(serializer.validated_data["password"]):
            return Response({"detail": "用户名或密码错误"}, status=status.HTTP_400_BAD_REQUEST)
        django_login(request, user, backend=backend)
        request.session.save()
        record_successful_login(request, user, "PASSWORD")
    return Response(authentication_payload(request))


@extend_schema(
    request=None,
    responses={200: AuthenticationStateSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def development_auto_login(request):
    """Retired: always require explicit credentials, even with old dev flags."""
    return Response({"detail": "请使用独立账号和密码登录。"}, status=status.HTTP_404_NOT_FOUND)


@extend_schema(
    request=None,
    responses={200: AuthenticationStateSerializer},
)
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def auth_logout(request):
    django_logout(request)
    return Response({"authenticated": False, "user": None})


@extend_schema(
    responses={200: AuthenticationStateSerializer},
)
@api_view(["GET"])
@permission_classes([AllowAny])
def current_user(request):
    get_token(request)
    return Response(authentication_payload(request))


def authentication_payload(request):
    authenticated = bool(request.user.is_authenticated)
    payload = {"authenticated": authenticated, "user": user_payload(request.user) if authenticated else None}
    state = identity.switch_state(request)
    if state is not None:
        payload["account_switch"] = state
    return payload


def switch_error(request, exc):
    return Response({"error": {"code": exc.code, "message": exc.message, "field_errors": {},
                              "request_id": getattr(request, "request_id", None)}}, status=exc.status)


IDENTITY_VERSION_PARAMETER = OpenApiParameter(
    name="X-Identity-Version", location=OpenApiParameter.HEADER, required=True,
    type=str, description="从 me 或 switch-targets 获取的不透明身份版本；每次切换/返回后更新。",
)
SWITCH_ERRORS = {
    400: OpenApiResponse(description="请求字段错误"),
    403: OpenApiResponse(description="管理员原登录、切换凭据或 CSRF 校验失败"),
    409: OpenApiResponse(description="身份版本冲突或员工状态已变化"),
    428: OpenApiResponse(description="缺少 X-Identity-Version"),
}


@extend_schema(parameters=[SwitchTargetQuerySerializer], responses={
    200: SwitchTargetsResponseSerializer, 400: OpenApiResponse(description="查询参数错误"),
    403: OpenApiResponse(description="仅有效原 admin 登录可查询"),
})
@api_view(["GET"])
@permission_classes([AllowAny])
def account_switch_targets(request):
    try:
        identity.authorize_switch(request)
    except identity.IdentitySwitchError as exc:
        return switch_error(request, exc)
    serializer = SwitchTargetQuerySerializer(data=request.query_params)
    serializer.is_valid(raise_exception=True)
    get_token(request)
    payload = switch_target_list(
        serializer.validated_data.get("q", ""),
        department_id=serializer.validated_data.get("department_id"),
        role_id=serializer.validated_data.get("role_id"),
    )
    return Response({**payload, "identity_version": identity.identity_version(request)})


@extend_schema(request=SwitchAccountSerializer, parameters=[IDENTITY_VERSION_PARAMETER], responses={
    200: AuthenticationStateSerializer, 404: OpenApiResponse(description="员工账号不存在或不可切换"),
    **SWITCH_ERRORS,
})
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def account_switch(request):
    serializer = SwitchAccountSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        identity.switch_account(request, serializer.validated_data["employee_id"])
    except identity.IdentitySwitchError as exc:
        return switch_error(request, exc)
    return Response(authentication_payload(request))


@extend_schema(request=ReturnAdminSerializer, parameters=[IDENTITY_VERSION_PARAMETER], responses={
    200: AuthenticationStateSerializer, **SWITCH_ERRORS,
})
@api_view(["POST"])
@permission_classes([AllowAny])
@csrf_protect
def account_return_admin(request):
    serializer = ReturnAdminSerializer(data=request.data)
    serializer.is_valid(raise_exception=True)
    try:
        identity.return_admin(request)
    except identity.IdentitySwitchError as exc:
        return switch_error(request, exc)
    return Response(authentication_payload(request))


@extend_schema(
    responses={
        200: HealthResponseSerializer,
        503: HealthResponseSerializer,
    },
)
@api_view(["GET"])
@permission_classes([AllowAny])
def health(request):
    checks = {"database": "error", "redis": "error"}
    errors = {}

    try:
        with connection.cursor() as cursor:
            cursor.execute("SELECT 1")
            cursor.fetchone()
        checks["database"] = "ok"
    except Exception as exc:
        errors["database"] = exc.__class__.__name__

    try:
        client = redis.Redis.from_url(settings.REDIS_URL, socket_connect_timeout=2, socket_timeout=2)
        if client.ping():
            checks["redis"] = "ok"
    except Exception as exc:
        errors["redis"] = exc.__class__.__name__

    healthy = all(value == "ok" for value in checks.values())
    payload = {
        "status": "ok" if healthy else "error",
        "service": "haiqu-backend",
        **checks,
    }
    if settings.DEBUG and errors:
        payload["errors"] = errors

    return Response(
        payload,
        status=status.HTTP_200_OK if healthy else status.HTTP_503_SERVICE_UNAVAILABLE,
    )
