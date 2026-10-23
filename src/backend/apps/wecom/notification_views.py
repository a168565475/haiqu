from django.utils.decorators import method_decorator
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework.permissions import IsAuthenticated
from rest_framework.response import Response
from rest_framework.exceptions import NotFound
from rest_framework.views import APIView

from apps.access_control.permissions import CanManageNotifications, CanManageWeCom, SuperadministratorOnly
from apps.core.api.permissions import HasActiveEmployee
from apps.core.auth import active_employee_for
from . import notification_selectors as selectors, notification_services as services
from . import notification_preview_selectors as preview_selectors, notification_preview_services as preview_services
from .models import NotificationPreviewAttempt
from .notification_catalog import get_event
from .notification_serializers import (
    NotificationListSerializer, NotificationPreviewResponseSerializer,
    NotificationPreviewSerializer, NotificationReadSerializer, NotificationRuleListSerializer,
    NotificationRuleResponseSerializer, NotificationRuleWriteSerializer, NotificationUnreadSerializer,
    NotificationQuerySerializer, NotificationDeliveryQuerySerializer, NotificationDeliveryListSerializer,
    NotificationPreviewSendSerializer, NotificationPreviewRecipientQuerySerializer,
)
from .views import IF_MATCH


@method_decorator(never_cache, name="dispatch")
@method_decorator(csrf_protect, name="dispatch")
class NotificationManagementView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanManageNotifications]


def _rule_response(rule):
    return Response(NotificationRuleResponseSerializer({"data": selectors.rule_payload(rule)}).data,
                    headers={"ETag": selectors.rule_etag(rule)})


class NotificationRulesView(NotificationManagementView):
    @extend_schema(responses=NotificationRuleListSerializer)
    def get(self, request):
        payload = {"data": selectors.all_rule_payloads(),
                   "roles": [selectors._role_payload(role) for role in selectors.roles_queryset()]}
        return Response(NotificationRuleListSerializer(payload).data)


class NotificationRuleDetailView(NotificationManagementView):
    @extend_schema(request=NotificationRuleWriteSerializer, responses=NotificationRuleResponseSerializer, parameters=[IF_MATCH])
    def patch(self, request, event_code):
        try:
            get_event(event_code)
        except ValueError:
            raise NotFound("通知规则不存在。") from None
        serializer = NotificationRuleWriteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        rule = services.update_rule(request, event_code, serializer.validated_data)
        return _rule_response(rule)


class NotificationRulePreviewView(NotificationManagementView):
    @extend_schema(request=NotificationPreviewSerializer, responses=NotificationPreviewResponseSerializer)
    def post(self, request, event_code):
        try:
            event = get_event(event_code)
        except ValueError:
            raise NotFound("通知规则不存在。") from None
        variables = NotificationPreviewSerializer(data=request.data)
        variables.is_valid(raise_exception=True)
        rule = selectors.rules_queryset().filter(event_code=event_code).first()
        source = selectors.rule_payload(rule) if rule else selectors.default_rule_payload(event)
        if request.headers.get("If-Match"):
            services.require_etag(request.headers["If-Match"], source["etag"])
        rule_payload = {key: source[key] for key in services.RULE_FIELDS}
        rule_payload.update({key: value for key, value in variables.validated_data.items() if key != "variables"})
        payload = services.preview_rule(event_code, rule_payload, variables.validated_data["variables"])
        payload = preview_services.signed_preview(request, event_code,
            {**rule_payload, "variables": variables.validated_data["variables"]}, source["etag"], payload)
        return Response(NotificationPreviewResponseSerializer({"data": payload}).data)


class NotificationPreviewManagementView(NotificationManagementView):
    permission_classes = [IsAuthenticated, HasActiveEmployee, CanManageNotifications, CanManageWeCom, SuperadministratorOnly]


class NotificationPreviewRecipientsView(NotificationPreviewManagementView):
    @extend_schema(parameters=[NotificationPreviewRecipientQuerySerializer], responses=OpenApiTypes.OBJECT)
    def get(self, request):
        query = NotificationPreviewRecipientQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        return Response(preview_selectors.recipient_options(**query.validated_data))


class NotificationPreviewSendView(NotificationPreviewManagementView):
    @extend_schema(request=NotificationPreviewSendSerializer, responses=OpenApiTypes.OBJECT)
    def post(self, request, event_code):
        try:
            get_event(event_code)
        except ValueError:
            raise NotFound("通知规则不存在。") from None
        preview_services.require_preview_schema()
        serializer = NotificationPreviewSendSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        attempt = preview_services.send_preview(request, event_code, serializer.validated_data)
        return Response({"data": preview_selectors.attempt_payload(attempt)})


class NotificationPreviewAttemptView(NotificationPreviewManagementView):
    @extend_schema(responses=OpenApiTypes.OBJECT)
    def get(self, request, preview_id):
        preview_services.require_preview_schema()
        attempt = NotificationPreviewAttempt.objects.filter(preview_id=preview_id,
            requested_by_employee=active_employee_for(request.user)).first()
        if attempt is None:
            raise NotFound("尚未找到本次发送记录，请稍后再次查询；不要重复发送。")
        return Response({"data": preview_selectors.attempt_payload(attempt)})


@method_decorator(never_cache, name="dispatch")
class NotificationPersonalView(APIView):
    permission_classes = [IsAuthenticated, HasActiveEmployee]


class NotificationInboxView(NotificationPersonalView):
    @extend_schema(responses=NotificationListSerializer)
    def get(self, request):
        employee = active_employee_for(request.user)
        if employee is None:
            return Response({"data": [], "count": 0, "page": 1, "page_size": 20})
        query = NotificationQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page, page_size = query.validated_data["page"], query.validated_data["page_size"]
        queryset = selectors.inbox_queryset(employee.pk)
        start = (page - 1) * page_size
        values = {"data": [selectors.recipient_payload(item, request.user) for item in queryset[start:start + page_size]],
                  "count": queryset.count(), "page": page, "page_size": page_size}
        return Response(NotificationListSerializer(values).data)


class NotificationUnreadCountView(NotificationPersonalView):
    @extend_schema(responses=NotificationUnreadSerializer)
    def get(self, request):
        employee = active_employee_for(request.user)
        return Response(NotificationUnreadSerializer({"unread_count": selectors.unread_count(employee.pk) if employee else 0}).data)


@method_decorator(csrf_protect, name="dispatch")
class NotificationReadView(NotificationPersonalView):
    @extend_schema(request=None, responses=NotificationReadSerializer)
    def post(self, request, recipient_id):
        employee = active_employee_for(request.user)
        recipient = services.mark_read(employee.pk, recipient_id)
        return Response(NotificationReadSerializer({"data": selectors.recipient_payload(recipient, request.user)}).data)


class NotificationTargetView(NotificationPersonalView):
    @extend_schema(request=None, responses=OpenApiTypes.OBJECT)
    def get(self, request, recipient_id):
        employee = active_employee_for(request.user)
        recipient = selectors.inbox_queryset(employee.pk).filter(pk=recipient_id).first()
        if recipient is None or not selectors.target_accessible(recipient, request.user) or recipient.event.target is None:
            raise NotFound("通知目标当前不可访问。")
        return Response({"data": {"target": recipient.event.target}})


class NotificationDeliveriesView(NotificationManagementView):
    @extend_schema(responses=NotificationDeliveryListSerializer)
    def get(self, request):
        query = NotificationDeliveryQuerySerializer(data=request.query_params)
        query.is_valid(raise_exception=True)
        page, page_size = query.validated_data["page"], query.validated_data["page_size"]
        status = query.validated_data.get("status")
        queryset = selectors.delivery_queryset()
        if status:
            queryset = queryset.filter(status=status)
        start = (page - 1) * page_size
        rows = [{"id": item.pk, "event_code": item.recipient.event.event_code,
                 "channel": item.channel, "status": item.status, "error_code": item.error_code,
                 "attempt_count": item.attempt_count, "created_at": item.created_at,
                 "last_attempt_at": item.last_attempt_at, "finished_at": item.finished_at}
                for item in queryset[start:start + page_size]]
        return Response(NotificationDeliveryListSerializer({"data": rows, "count": queryset.count(), "page": page, "page_size": page_size}).data)
