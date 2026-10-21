from apps.access_control.resource_scopes import filter_crafts, enabled
from rest_framework import serializers, viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from drf_spectacular.utils import extend_schema

from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.workshop_config.models import Craft, OutsourcingCode

from ..models import OutsourcingFactory, OutsourcingOrder, OutsourcingOrderStatus
from ..selectors import factories_with_context
from ..unified_selectors import (
    SOURCE_GROUP_LABELS, SOURCE_LABELS, VIEW_PERMISSIONS, UnifiedOrderFilters, unified_order_candidates, unified_order_rows,
)


class UnifiedOutsourcingSummarySerializer(serializers.Serializer):
    """统一列表摘要由选择器生成；提供独立名称供接口文档引用。"""


class UnifiedOutsourcingOrderViewSet(viewsets.GenericViewSet):
    """只读聚合；写入仍交由原业务接口的权限、并发和库存校验。"""

    queryset = OutsourcingOrder.objects.none()
    serializer_class = UnifiedOutsourcingSummarySerializer
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    action_permission_map = {"list": VIEW_PERMISSIONS, "options": VIEW_PERMISSIONS}

    @extend_schema(parameters=[UnifiedOrderFilters])
    def list(self, request):
        filters = UnifiedOrderFilters(data=request.query_params)
        filters.is_valid(raise_exception=True)
        values = filters.validated_data
        page = list(self.paginate_queryset(unified_order_candidates(request, values)))
        return self.get_paginated_response(unified_order_rows(request, page, values))

    @action(detail=False, methods=["get"])
    def options(self, request):
        regular = request.user.has_perm(VIEW_PERMISSIONS[0])
        codes = OutsourcingCode.values if regular else ["POWDER_COATING"]
        crafts = Craft.objects.filter(craft_type="EXTERNAL", status="ACTIVE", outsourcing_code__in=codes).order_by("name", "id")
        if enabled():
            regular_crafts = filter_crafts(crafts, request, VIEW_PERMISSIONS[0], "pk") if regular else crafts.none()
            metal_crafts = filter_crafts(crafts.filter(outsourcing_code="POWDER_COATING"), request, VIEW_PERMISSIONS[1], "pk") if request.user.has_perm(VIEW_PERMISSIONS[1]) else crafts.none()
            crafts = (regular_crafts | metal_crafts).distinct()
        visible_craft_ids = set(crafts.values_list("pk", flat=True))
        factories = OutsourcingFactory.objects.filter(status="ACTIVE")
        if not regular or enabled():
            factories = factories.filter(craft_links__craft__in=crafts).distinct()
        return Response({"data": {
            "crafts": [{"id": str(row.pk), "name": row.name, "outsourcing_code": row.outsourcing_code} for row in crafts],
            "factories": [{"id": str(row.pk), "name": row.name, "crafts": [
                {"id": str(link.craft_id), "name": link.craft_name_snapshot} for link in row.prefetched_craft_links if not enabled() or link.craft_id in visible_craft_ids
            ]} for row in factories_with_context(factories).order_by("name", "id")],
            "statuses": [{"value": value, "label": label} for value, label in [
                *OutsourcingOrderStatus.choices, ("PENDING_HANDOFF", "待交接"),
            ]],
            "source_kinds": [{"value": value, "label": label} for value, label in SOURCE_LABELS.items()],
            "source_groups": [{"value": value, "label": label} for value, label in SOURCE_GROUP_LABELS.items()],
        }})
