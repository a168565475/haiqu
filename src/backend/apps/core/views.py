import redis
from django.conf import settings
from django.contrib.auth import authenticate, login as django_login, logout as django_logout
from django.core.exceptions import ObjectDoesNotExist
from django.db import connection
from django.middleware.csrf import get_token
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework import status
from rest_framework.decorators import api_view, permission_classes
from rest_framework.permissions import AllowAny
from rest_framework.response import Response

from apps.organizations.models import EmployeeStatus

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

    return {
        "id": user.pk,
        "username": user.get_username(),
        "display_name": user.get_full_name() or user.get_username(),
        "employee": employee_payload,
        "permissions": sorted(user.get_all_permissions()),
        "data_scope": data_scope,
    }


def can_login_to_erp(user):
    if not user.is_active:
        return False
    if user.is_superuser:
        return True

    try:
        employee = user.employee_profile
    except ObjectDoesNotExist:
        return False

    return employee.status == EmployeeStatus.ACTIVE and employee.archived_at is None


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
    if user is None or not can_login_to_erp(user):
        return Response(
            {"detail": "用户名或密码错误"},
            status=status.HTTP_400_BAD_REQUEST,
        )

    django_login(request, user)
    return Response({"authenticated": True, "user": user_payload(user)})


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
