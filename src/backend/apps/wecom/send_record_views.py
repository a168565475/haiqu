from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.access_control.permissions import CanManageNotifications, CanManageWeCom, SuperadministratorOnly
from apps.core.api.permissions import HasActiveEmployee
from . import message_selectors, notification_preview_selectors
from .send_record_selectors import send_record_payload, send_records_queryset
from .send_record_serializers import SendRecordListSerializer, SendRecordQuerySerializer
from .views import WeComUnavailable


SOURCE_PERMISSIONS = {
    "BUSINESS": (CanManageNotifications,),
    "RULE_PREVIEW": (CanManageNotifications, CanManageWeCom, SuperadministratorOnly),
    "MESSAGE_TEST": (CanManageWeCom,),
}


@method_decorator(never_cache, name="dispatch")
class NotificationSendRecordsView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]

    @extend_schema(parameters=[SendRecordQuerySerializer], responses=SendRecordListSerializer,
        description="按来源分页读取企业微信发送记录，默认自动业务通知，仅含企微渠道。"
                    "规则卡片试发只返回当前发起人的记录；各来源沿用原管理权限。"
                    "正文为已保存快照，ACCEPTED 仅表示企微受理，不代表送达或已读。")
    def get(self, request):
        query = SendRecordQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        params = query.validated_data
        source = params["source"]
        for permission_class in SOURCE_PERMISSIONS[source]:
            permission = permission_class()
            if not permission.has_permission(request, self):
                self.permission_denied(request, message=permission.message)
        if ((source == "RULE_PREVIEW" and not notification_preview_selectors.schema_ready())
                or (source == "MESSAGE_TEST" and not message_selectors.schema_is_ready())):
            raise WeComUnavailable()
        queryset = send_records_queryset(source, request.employee.pk, params.get("status"))
        page, page_size = params["page"], params["page_size"]
        start = (page - 1) * page_size
        result = {
            "data": [send_record_payload(row, source) for row in queryset[start:start + page_size]],
            "count": queryset.count(), "page": page, "page_size": page_size,
        }
        return Response(SendRecordListSerializer(result).data)
