from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from drf_spectacular.utils import OpenApiParameter, OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access_control.permissions import CanManageAccounts, SuperadministratorOnly
from apps.core.api.permissions import HasActiveEmployee
from . import directory_services
from . import directory_progress
from .directory_serializers import (
    DirectoryMatchResponseSerializer, DirectoryMatchSerializer,
    DirectoryPreviewQuerySerializer, DirectoryPreviewResponseSerializer, DirectorySyncResponseSerializer, DirectorySyncSerializer,
    DirectoryProgressResponseSerializer,
)
from .views import IF_MATCH, ManagementView


ERROR_RESPONSES = {
    400: OpenApiResponse(description="输入或预览令牌无效"),
    401: OpenApiResponse(description="未登录或登录会话无效"),
    403: OpenApiResponse(description="账号无权限、已失效或 CSRF 校验失败"),
    409: OpenApiResponse(description="配置未就绪、待核对成员、员工不可用或身份冲突"),
    412: OpenApiResponse(description="目录、配置或员工版本已变化"),
    428: OpenApiResponse(description="缺少 If-Match"),
    502: OpenApiResponse(description="上游读取失败，未执行本次业务写入"),
    503: OpenApiResponse(description="模块未启用或迁移未就绪"),
}
PROGRESS_HEADER = OpenApiParameter("X-Directory-Progress", str, OpenApiParameter.HEADER,
                                   description="可选的一次性 UUID，用于查询当前用户此次请求的真实进度")


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("preview_token"), name="dispatch")
class DirectoryManagementView(ManagementView):
    # 读取通讯录和建档仅使用员工账号管理权限，不返回配置或解密后的凭据。
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanManageAccounts]


class DirectoryPreviewView(DirectoryManagementView):
    @extend_schema(parameters=[DirectoryPreviewQuerySerializer, PROGRESS_HEADER], responses={200: DirectoryPreviewResponseSerializer, **ERROR_RESPONSES})
    @sensitive_variables()
    def get(self, request):
        query = DirectoryPreviewQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        with directory_progress.track(request, 3):
            data, etag = directory_services.preview_directory(request, refresh=False, **query.validated_data)
            return Response(DirectoryPreviewResponseSerializer({"data": data}).data, headers={"ETag": etag})


class DirectoryRefreshView(DirectoryManagementView):
    @extend_schema(request=DirectoryPreviewQuerySerializer, parameters=[PROGRESS_HEADER],
                   responses={200: DirectoryPreviewResponseSerializer, **ERROR_RESPONSES})
    @sensitive_variables()
    def post(self, request):
        serializer = DirectoryPreviewQuerySerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with directory_progress.track(request, 3):
            data, etag = directory_services.preview_directory(request, refresh=True, **serializer.validated_data)
            return Response(DirectoryPreviewResponseSerializer({"data": data}).data, headers={"ETag": etag})


class DirectorySyncView(DirectoryManagementView):
    permission_classes = [*DirectoryManagementView.permission_classes, SuperadministratorOnly]

    @extend_schema(request=DirectorySyncSerializer, parameters=[IF_MATCH, PROGRESS_HEADER],
                   responses={200: DirectorySyncResponseSerializer, **ERROR_RESPONSES})
    @sensitive_variables()
    def post(self, request):
        serializer = DirectorySyncSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with directory_progress.track(request, len(serializer.validated_data["user_ids"]) + 2):
            data = directory_services.sync_directory(request, serializer.validated_data)
            return Response(DirectorySyncResponseSerializer({"data": data}).data)


class DirectoryMatchView(DirectoryManagementView):
    permission_classes = [*DirectoryManagementView.permission_classes, SuperadministratorOnly]

    @extend_schema(request=DirectoryMatchSerializer, parameters=[IF_MATCH, PROGRESS_HEADER],
                   responses={200: DirectoryMatchResponseSerializer, 404: OpenApiResponse(description="员工不存在"), **ERROR_RESPONSES})
    @sensitive_variables()
    def post(self, request):
        serializer = DirectoryMatchSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        with directory_progress.track(request, 1):
            data = directory_services.match_directory_employee(request, serializer.validated_data)
            return Response(DirectoryMatchResponseSerializer({"data": data}).data)


class DirectoryProgressView(DirectoryManagementView):
    @extend_schema(responses={200: DirectoryProgressResponseSerializer, 404: OpenApiResponse(description="进度不存在或已过期"), **ERROR_RESPONSES})
    def get(self, request, progress_id):
        directory_services.require_access(request)
        return Response(DirectoryProgressResponseSerializer({"data": directory_progress.read(request, progress_id)}).data)
