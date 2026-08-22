import uuid

from django.utils.dateparse import parse_datetime
from rest_framework import mixins
from rest_framework.exceptions import NotFound, ValidationError
from rest_framework.response import Response

from apps.customers.api.views import CustomerApiViewSetBase
from apps.customers.selectors import accessible_customers

from ..models import AuditLog
from .serializers import AuditLogSerializer


def _filtered_logs(request, queryset):
    exact_filters = {"object_type": "object_type", "action": "action", "context_type": "context_type"}
    for parameter, field_name in exact_filters.items():
        value = request.query_params.get(parameter)
        if value:
            queryset = queryset.filter(**{field_name: value})
    for parameter, field_name in {
        "actor_employee_id": "actor_employee_id", "context_id": "context_id", "object_id": "object_id"
    }.items():
        value = request.query_params.get(parameter)
        if value:
            try:
                value = uuid.UUID(value)
            except (TypeError, ValueError) as exc:
                raise ValidationError({parameter: "必须是合法 UUID。"}) from exc
            queryset = queryset.filter(**{field_name: value})
    for parameter, lookup in [("occurred_from", "occurred_at__gte"), ("occurred_to", "occurred_at__lte")]:
        value = request.query_params.get(parameter)
        if value:
            parsed = parse_datetime(value)
            if parsed is None:
                raise ValidationError({parameter: "必须是合法的 ISO 8601 日期时间。"})
            queryset = queryset.filter(**{lookup: parsed})
    return queryset.order_by("-occurred_at", "-id")


class AuditLogViewSet(mixins.ListModelMixin, mixins.RetrieveModelMixin, CustomerApiViewSetBase):
    serializer_class = AuditLogSerializer
    action_permission_map = {
        "list": "audit.view_all_auditlog",
        "retrieve": "audit.view_all_auditlog",
    }

    def get_queryset(self):
        return _filtered_logs(
            self.request,
            AuditLog.objects.select_related("actor_employee").all(),
        )

    def retrieve(self, request, *args, **kwargs):
        return Response({"data": self.get_serializer(self.get_object()).data})


class CustomerAuditLogNestedViewSet(CustomerApiViewSetBase):
    queryset = AuditLog.objects.none()
    serializer_class = AuditLogSerializer
    action_permission_map = {"list": "audit.view_auditlog"}

    def list(self, request, *args, **kwargs):
        customer = accessible_customers(request, "view_auditlog").filter(pk=self.kwargs["customer_pk"]).first()
        if customer is None:
            raise NotFound("客户不存在或无权查看其审计日志。")
        queryset = _filtered_logs(
            request,
            AuditLog.objects.select_related("actor_employee").filter(
                context_type="CUSTOMER_ACCOUNT", context_id=customer.pk
            ),
        )
        page = self.paginate_queryset(queryset)
        data = AuditLogSerializer(page or queryset, many=True).data
        return self.get_paginated_response(data) if page is not None else Response({"data": data})
