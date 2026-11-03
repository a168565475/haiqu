from django.db import ProgrammingError, transaction
from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_variables
from drf_spectacular.utils import OpenApiParameter, extend_schema
from rest_framework.exceptions import APIException
from rest_framework.permissions import BasePermission, IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.permissions import HasActiveEmployee
from . import selectors, services
from .models import CodexConnection
from .runtime_client import RuntimeFailure
from .serializers import (CancelSerializer, ChallengeQuerySerializer, ChallengeResponseSerializer,
                          EmptySerializer, ModelSerializer, SnapshotResponseSerializer)


IF_MATCH = OpenApiParameter('If-Match', str, OpenApiParameter.HEADER, required=True)
ETAG = OpenApiParameter('ETag', str, OpenApiParameter.HEADER, required=True, response=True)


class CodexSchemaUnavailable(APIException):
    status_code = 503
    default_detail = 'Codex 连接模块尚未完成数据库迁移。'
    api_error_code = 'CODEX_SCHEMA_UNAVAILABLE'


class CodexRuntimeUnavailable(APIException):
    status_code = 502
    default_detail = 'Codex 运行服务暂不可用，请稍后刷新。'
    api_error_code = 'CODEX_RUNTIME_UNAVAILABLE'


class CanManageCodex(BasePermission):
    def has_permission(self, request, view):
        services.require_actor(request)
        return True


@method_decorator(never_cache, name='dispatch')
class ManagementView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanManageCodex]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        if not selectors.schema_is_ready():
            raise CodexSchemaUnavailable()

    def handle_exception(self, exc):
        if isinstance(exc, RuntimeFailure):
            safe = CodexRuntimeUnavailable()
            safe.api_error_code = 'CODEX_' + exc.code
            if exc.code in ('NOT_FOUND', 'NOT_READY', 'BUSY'):
                safe.status_code = 409
                safe.detail = '当前授权操作尚未就绪或已发生变化，请刷新。'
            exc = safe
        elif isinstance(exc, ProgrammingError) and getattr(exc.__cause__, 'sqlstate', None) == '42P01':
            exc = CodexSchemaUnavailable()
        return super().handle_exception(exc)


def snapshot_response(connection, request, *, status=200):
    # worker 可能已在入队事务提交后完成；状态、操作和 ETag 必须来自同一锁定快照。
    with transaction.atomic():
        connection = CodexConnection.objects.select_for_update().first() or connection
        payload = selectors.connection_snapshot(connection, request.employee.id)
        return Response(SnapshotResponseSerializer({'data': payload}).data, status=status,
                        headers={'ETag': selectors.connection_etag(connection)})


class ConnectionView(ManagementView):
    @extend_schema(responses=SnapshotResponseSerializer, parameters=[ETAG])
    def get(self, request):
        return snapshot_response(selectors.get_connection(), request)


class OperationView(ManagementView):
    action = None

    @extend_schema(request={'application/json': {'type': 'object', 'properties': {}, 'additionalProperties': False}},
                   responses={202: SnapshotResponseSerializer}, parameters=[IF_MATCH, ETAG])
    def post(self, request):
        serializer = EmptySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return snapshot_response(services.enqueue(request, self.action), request, status=202)


class CancelView(ManagementView):
    @extend_schema(request=CancelSerializer, responses={202: SnapshotResponseSerializer}, parameters=[IF_MATCH, ETAG])
    def post(self, request):
        serializer = CancelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return snapshot_response(services.cancel_login(request, serializer.validated_data['operation_id']), request, status=202)


class ModelView(ManagementView):
    @extend_schema(request={'application/json': {'type': 'object', 'properties': {'model': {'type': 'string', 'minLength': 1, 'maxLength': 200}},
                                                'required': ['model'], 'additionalProperties': False}},
                   responses=SnapshotResponseSerializer, parameters=[IF_MATCH, ETAG])
    def patch(self, request):
        serializer = ModelSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        return snapshot_response(services.select_model(request, serializer.validated_data['model']), request)


class ChallengeView(ManagementView):
    @extend_schema(parameters=[ChallengeQuerySerializer], responses=ChallengeResponseSerializer)
    @sensitive_variables()
    def get(self, request):
        serializer = ChallengeQuerySerializer(data=request.query_params)
        serializer.is_valid(raise_exception=True)
        challenge = services.login_challenge(request, serializer.validated_data['operation_id'])
        return Response(ChallengeResponseSerializer({'data': challenge}).data)
