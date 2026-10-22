from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.debug import sensitive_post_parameters, sensitive_variables
from drf_spectacular.utils import OpenApiResponse, extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response

from apps.access_control.permissions import CanManageOrganization
from apps.core.api.permissions import HasActiveEmployee
from . import department_mapping_services as services
from .department_mapping_serializers import (
    DepartmentMappingPreviewResponseSerializer, DepartmentMappingResponseSerializer, DepartmentMappingWriteSerializer,
)
from .views import IF_MATCH, ManagementView
from .directory_serializers import StrictSerializer


ERROR_RESPONSES = {
    400: OpenApiResponse(description="参数、确认或预览令牌无效"),
    401: OpenApiResponse(description="未登录"),
    403: OpenApiResponse(description="缺少组织管理权限或 CSRF 校验失败"),
    404: OpenApiResponse(description="来源部门或 ERP 部门不存在"),
    409: OpenApiResponse(description="配置未就绪或目标部门不可用"),
    412: OpenApiResponse(description="来源目录、配置、映射或 ERP 组织已变化"),
    428: OpenApiResponse(description="缺少 If-Match"),
    502: OpenApiResponse(description="企业微信读取失败"),
    503: OpenApiResponse(description="模块或数据库迁移尚未就绪"),
}


@method_decorator(never_cache, name="dispatch")
@method_decorator(sensitive_post_parameters("preview_token"), name="dispatch")
class DepartmentMappingManagementView(ManagementView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanManageOrganization]

    def initial(self, request, *args, **kwargs):
        super().initial(request, *args, **kwargs)
        services.require_schema()


class DepartmentMappingsView(DepartmentMappingManagementView):
    @extend_schema(responses={200: DepartmentMappingPreviewResponseSerializer, **ERROR_RESPONSES})
    @sensitive_variables()
    def get(self, request):
        data, etag = services.preview_mappings(request, refresh=False)
        return Response(DepartmentMappingPreviewResponseSerializer({"data": data}).data, headers={"ETag": etag})


class DepartmentMappingsRefreshView(DepartmentMappingManagementView):
    @extend_schema(request=StrictSerializer,
                   responses={200: DepartmentMappingPreviewResponseSerializer, **ERROR_RESPONSES})
    @sensitive_variables()
    def post(self, request):
        serializer = StrictSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data, etag = services.preview_mappings(request, refresh=True)
        return Response(DepartmentMappingPreviewResponseSerializer({"data": data}).data, headers={"ETag": etag})


class DepartmentMappingDetailView(DepartmentMappingManagementView):
    @extend_schema(request=DepartmentMappingWriteSerializer, parameters=[IF_MATCH],
                   responses={200: DepartmentMappingResponseSerializer, **ERROR_RESPONSES})
    @sensitive_variables()
    def put(self, request, department_id):
        serializer = DepartmentMappingWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = services.update_mapping(request, department_id, serializer.validated_data)
        return Response(DepartmentMappingResponseSerializer({"data": data}).data)
