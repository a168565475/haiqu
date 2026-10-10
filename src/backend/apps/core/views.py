import redis
from django.conf import settings
from django.contrib.auth import authenticate, get_user_model, login as django_login, logout as django_logout
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection, transaction
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from .auth import can_access_erp
from .serializers import AuthenticationStateSerializer, HealthResponseSerializer, LoginSerializer


def user_payload(user):
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
    if settings.ACCESS_MANAGEMENT_ENABLED:
        from apps.access_control.selectors import effective_access
        payload["effective_access"] = effective_access(user)
    from apps.access_control import sales_policy
    payload["sales_access_enabled"] = sales_policy.enabled()
    from apps.access_control import module_policy
    payload['module_access_enabled'] = module_policy.enabled()
    if module_policy.enabled():
        from types import SimpleNamespace
        request = SimpleNamespace(user=user, employee=employee)
        payload['permissions'] = sorted(set(payload['permissions']) | {
            code for code in module_policy.LEGACY_ALIASES if module_policy.has_permission(request, code)})
    if sales_policy.enabled():
        from types import SimpleNamespace
        request = SimpleNamespace(user=user, employee=employee)
        payload["permissions"] = sorted(set(payload["permissions"]) | {code for code in sales_policy.LEGACY_ACTION_PERMISSIONS if sales_policy.has_permission(request, code)})
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
        backend = user.backend
        user = get_user_model().objects.select_for_update().get(pk=user.pk)
        if not can_access_erp(user) or not user.check_password(serializer.validated_data["password"]):
            return Response({"detail": "用户名或密码错误"}, status=status.HTTP_400_BAD_REQUEST)
        django_login(request, user, backend=backend)
        request.session.save()
    return Response({"authenticated": True, "user": user_payload(user)})


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
    if not request.user.is_authenticated:
        return Response({"authenticated": False, "user": None})

    return Response({"authenticated": True, "user": user_payload(request.user)})


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
