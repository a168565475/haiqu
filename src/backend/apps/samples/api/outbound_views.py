from django.db.models import Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.customers.api.views import CustomerApiViewSetBase, UUID_URL_REGEX

from ..models import SampleOutboundMethod
from ..outbound_filters import SampleInventoryOutboundLineFilter
from ..outbound_selectors import (
    available_sample_inventory_lines,
    sample_inventory_outbounds_with_detail,
    sample_outbound_lines_with_context,
)
from ..outbound_services import (
    create_sample_inventory_outbound,
    delete_sample_inventory_outbound,
)
from .outbound_serializers import (
    SampleOutboundCreateSerializer,
    SampleOutboundCreatedEnvelopeSerializer,
    SampleOutboundDetailEnvelopeSerializer,
    SampleOutboundDetailSerializer,
    SampleOutboundEligibleEnvelopeSerializer,
    SampleOutboundEligibleInventoryLineSerializer,
    SampleInventoryOutboundLineSerializer,
    SampleOutboundOptionsEnvelopeSerializer,
    SampleOutboundSummaryEnvelopeSerializer,
)


class SampleInventoryOutboundLineViewSet(mixins.ListModelMixin, CustomerApiViewSetBase):
    serializer_class = SampleInventoryOutboundLineSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SampleInventoryOutboundLineFilter
    search_fields = [
        "outbound__outbound_number",
        "inventory_line__sample_item__sample_request__request_number",
        "inventory_line__product_name_snapshot",
        "tracking_number",
        "remark",
    ]
    ordering_fields = ["outbound__operated_at", "outbound_quantity", "outbound_method"]
    ordering = ["-outbound__operated_at", "-id"]
    action_permission_map = {
        "list": "samples.view_sampleinventoryoutboundline",
        "summary": "samples.view_sampleinventoryoutboundline",
        "options": "samples.view_sampleinventoryoutboundline",
        "eligible": "samples.add_sampleinventoryoutbound",
        "documents": "samples.add_sampleinventoryoutbound",
        "document_detail": "samples.view_sampleinventoryoutboundline",
        "document_detail.DELETE": "samples.delete_sampleinventoryoutbound",
    }

    def get_queryset(self):
        return sample_outbound_lines_with_context()

    @extend_schema(responses=SampleOutboundSummaryEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        totals = self.get_queryset().aggregate(
            outbound_today=Coalesce(
                Sum("outbound_quantity", filter=Q(outbound__operated_at__date=today)),
                Value(0),
            ),
            outbound_this_month=Coalesce(
                Sum("outbound_quantity", filter=Q(outbound__operated_at__date__gte=month_start)),
                Value(0),
            ),
            mailed=Coalesce(
                Sum(
                    "outbound_quantity",
                    filter=Q(outbound_method=SampleOutboundMethod.MERCHANDISER_MAIL),
                ),
                Value(0),
            ),
            salesperson_carried=Coalesce(
                Sum(
                    "outbound_quantity",
                    filter=Q(outbound_method=SampleOutboundMethod.SALESPERSON_CARRY),
                ),
                Value(0),
            ),
        )
        return Response({"data": totals})

    @extend_schema(responses=SampleOutboundOptionsEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="options")
    def options(self, request):
        categories = list(
            self.get_queryset()
            .exclude(inventory_line__category_name_snapshot="")
            .order_by("inventory_line__category_name_snapshot")
            .values_list("inventory_line__category_name_snapshot", flat=True)
            .distinct()
        )
        methods = [{"value": value, "label": label} for value, label in SampleOutboundMethod.choices]
        return Response({"data": {"outbound_methods": methods, "product_categories": categories}})

    @extend_schema(responses=SampleOutboundEligibleEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="eligible")
    def eligible(self, request):
        queryset = available_sample_inventory_lines()
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(receipt__receipt_number__icontains=keyword)
                | Q(sample_item__sample_request__request_number__icontains=keyword)
                | Q(product_name_snapshot__icontains=keyword)
            )
        page = self.paginate_queryset(queryset)
        serializer = SampleOutboundEligibleInventoryLineSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @extend_schema(
        request=SampleOutboundCreateSerializer,
        responses=SampleOutboundCreatedEnvelopeSerializer,
    )
    @action(detail=False, methods=["post"], url_path="documents")
    def documents(self, request):
        serializer = SampleOutboundCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        outbound = create_sample_inventory_outbound(
            items=serializer.validated_data["items"],
            actor_employee=self.actor_employee(),
        )
        return Response(
            {
                "data": {
                    "outbound_id": outbound.pk,
                    "outbound_number": outbound.outbound_number,
                    "operated_by": outbound.operated_by_employee.display_name,
                    "operated_at": outbound.operated_at,
                    "line_count": outbound.created_line_count,
                }
            },
            status=201,
        )

    @extend_schema(responses={200: SampleOutboundDetailEnvelopeSerializer, 204: None})
    @action(
        detail=False,
        methods=["get", "delete"],
        url_path=rf"documents/(?P<outbound_id>{UUID_URL_REGEX})",
    )
    def document_detail(self, request, outbound_id=None):
        if request.method == "DELETE":
            delete_sample_inventory_outbound(
                outbound_id=outbound_id,
                actor_employee=self.actor_employee(),
            )
            return Response(status=204)
        outbound = get_object_or_404(sample_inventory_outbounds_with_detail(), pk=outbound_id)
        return Response({"data": SampleOutboundDetailSerializer(outbound).data})
