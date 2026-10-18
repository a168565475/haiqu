from datetime import timedelta

from django.db.models import ExpressionWrapper, F, IntegerField, Q, Sum, Value
from django.db.models.functions import Coalesce
from django.utils import timezone
from django.shortcuts import get_object_or_404
from django_filters.rest_framework import DjangoFilterBackend
from drf_spectacular.utils import extend_schema
from rest_framework import filters, mixins
from rest_framework.decorators import action
from rest_framework.response import Response

from apps.customers.api.views import CustomerApiViewSetBase, UUID_URL_REGEX
from apps.inventory.models import RecordStatus, Warehouse, WarehouseLocation, WarehouseType, WarehouseZone

from ..inventory_filters import SampleInventoryLineFilter
from ..inventory_selectors import (
    eligible_sample_items_for_inventory,
    sample_inventory_lines_with_context,
    sample_inventory_receipts_with_detail,
)
from ..inventory_services import (
    create_sample_inventory_receipt,
    delete_sample_inventory_receipt,
)
from ..models import SampleInventoryLoanLine, SampleInventoryOutboundLine
from .inventory_serializers import (
    SampleInventoryLineSerializer,
    SampleInventoryEligibleEnvelopeSerializer,
    SampleInventoryEligibleItemSerializer,
    SampleInventoryOptionsEnvelopeSerializer,
    SampleInventoryReceiptCreateSerializer,
    SampleInventoryReceiptCreatedEnvelopeSerializer,
    SampleInventoryReceiptDetailEnvelopeSerializer,
    SampleInventoryReceiptDetailSerializer,
    SampleInventorySummaryEnvelopeSerializer,
)


class SampleInventoryLineViewSet(mixins.ListModelMixin, CustomerApiViewSetBase):
    serializer_class = SampleInventoryLineSerializer
    filter_backends = [DjangoFilterBackend, filters.SearchFilter, filters.OrderingFilter]
    filterset_class = SampleInventoryLineFilter
    search_fields = [
        "receipt__receipt_number",
        "sample_item__sample_request__request_number",
        "product_name_snapshot",
    ]
    ordering_fields = ["receipt__submitted_at", "received_quantity", "location"]
    ordering = ["-receipt__submitted_at", "-id"]
    action_permission_map = {
        "list": "samples.view_sampleinventoryline",
        "summary": "samples.view_sampleinventoryline",
        "options": "samples.view_sampleinventoryline",
        "eligible": "samples.add_sampleinventoryreceipt",
        "finished_goods_options": "samples.add_sampleinventoryreceipt",
        "receipts": "samples.add_sampleinventoryreceipt",
        "receipt_detail": "samples.view_sampleinventoryline",
        "receipt_detail.DELETE": "samples.delete_sampleinventoryreceipt",
    }

    def base_queryset(self):
        return sample_inventory_lines_with_context()

    def get_queryset(self):
        queryset = self.base_queryset()
        if self.request.query_params.get("inventory_status"):
            return queryset
        return queryset.filter(available_quantity__gt=0)

    @extend_schema(responses=SampleInventorySummaryEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        today = timezone.localdate()
        month_start = today.replace(day=1)
        next_month_start = (month_start + timedelta(days=32)).replace(day=1)
        visible_inventory_lines = self.base_queryset()
        available_expression = ExpressionWrapper(
            F("received_quantity") - F("outbound_quantity") - F("loaned_quantity"),
            output_field=IntegerField(),
        )
        totals = visible_inventory_lines.aggregate(
            current_available=Coalesce(Sum(available_expression), Value(0)),
            borrowed=Coalesce(Sum("loaned_quantity"), Value(0)),
            inbound_today=Coalesce(
                Sum(
                    "received_quantity",
                    filter=Q(receipt__submitted_at__date=today),
                ),
                Value(0),
            ),
            inbound_this_month=Coalesce(
                Sum(
                    "received_quantity",
                    filter=Q(
                        receipt__submitted_at__date__gte=month_start,
                        receipt__submitted_at__date__lt=next_month_start,
                    ),
                ),
                Value(0),
            ),
        )
        outbound_totals = SampleInventoryOutboundLine.objects.filter(
            inventory_line__in=visible_inventory_lines,
        ).aggregate(
            outbound_today=Coalesce(
                Sum("outbound_quantity", filter=Q(outbound__operated_at__date=today)),
                Value(0),
            ),
            outbound_this_month=Coalesce(
                Sum(
                    "outbound_quantity",
                    filter=Q(
                        outbound__operated_at__date__gte=month_start,
                        outbound__operated_at__date__lt=next_month_start,
                    ),
                ),
                Value(0),
            ),
        )
        loaned_this_month = SampleInventoryLoanLine.objects.filter(
            inventory_line__in=visible_inventory_lines,
            loan__operated_at__date__gte=month_start,
            loan__operated_at__date__lt=next_month_start,
        ).aggregate(total=Coalesce(Sum("loan_quantity"), Value(0)))["total"]
        return Response({"data": {
            **totals,
            **outbound_totals,
            "month": month_start.strftime("%Y-%m"),
            "loaned_this_month": loaned_this_month,
        }})

    @extend_schema(responses=SampleInventoryOptionsEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="options")
    def options(self, request):
        queryset = self.get_queryset()
        categories = list(
            queryset.exclude(category_name_snapshot="")
            .order_by("category_name_snapshot")
            .values_list("category_name_snapshot", flat=True)
            .distinct()
        )
        locations = list(
            queryset.exclude(location="")
            .order_by("location")
            .values_list("location", flat=True)
            .distinct()
        )
        return Response({"data": {"product_categories": categories, "locations": locations}})

    @extend_schema(responses=SampleInventoryEligibleEnvelopeSerializer)
    @action(detail=False, methods=["get"], url_path="eligible")
    def eligible(self, request):
        queryset = eligible_sample_items_for_inventory()
        keyword = request.query_params.get("q", "").strip()
        if keyword:
            queryset = queryset.filter(
                Q(sample_request__request_number__icontains=keyword)
                | Q(product_description_snapshot__icontains=keyword)
                | Q(sample_product__product_name__icontains=keyword)
            )
        page = self.paginate_queryset(queryset)
        serializer = SampleInventoryEligibleItemSerializer(page, many=True)
        return self.get_paginated_response(serializer.data)

    @action(detail=False, methods=["get"], url_path="finished-goods-options")
    def finished_goods_options(self, request):
        warehouses = Warehouse.objects.filter(
            status=RecordStatus.ACTIVE,
            warehouse_type=WarehouseType.FINISHED,
        ).order_by("warehouse_number", "id")
        zones = WarehouseZone.objects.filter(
            status=RecordStatus.ACTIVE,
            warehouse__status=RecordStatus.ACTIVE,
            warehouse__warehouse_type=WarehouseType.FINISHED,
        ).select_related("warehouse").order_by("warehouse__warehouse_number", "zone_name", "id")
        locations = WarehouseLocation.objects.filter(
            status=RecordStatus.ACTIVE,
            zone__status=RecordStatus.ACTIVE,
            zone__warehouse__status=RecordStatus.ACTIVE,
            zone__warehouse__warehouse_type=WarehouseType.FINISHED,
        ).select_related("zone", "zone__warehouse").order_by(
            "zone__warehouse__warehouse_number", "zone__zone_name", "location_number", "id"
        )
        return Response({"data": {
            "warehouses": [
                {"id": item.pk, "warehouse_number": item.warehouse_number, "warehouse_name": item.warehouse_name}
                for item in warehouses
            ],
            "zones": [
                {"id": item.pk, "warehouse_id": item.warehouse_id, "zone_name": item.zone_name}
                for item in zones
            ],
            "locations": [
                {
                    "id": item.pk,
                    "warehouse_id": item.zone.warehouse_id,
                    "zone_id": item.zone_id,
                    "location_number": item.location_number,
                }
                for item in locations
            ],
        }})

    @extend_schema(
        request=SampleInventoryReceiptCreateSerializer,
        responses=SampleInventoryReceiptCreatedEnvelopeSerializer,
    )
    @action(detail=False, methods=["post"], url_path="receipts")
    def receipts(self, request):
        serializer = SampleInventoryReceiptCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        receipt = create_sample_inventory_receipt(
            items=serializer.validated_data["items"],
            finished_goods_destination=serializer.validated_data["finished_goods_destination"],
            actor_employee=self.actor_employee(),
            request=request,
        )
        return Response(
            {
                "data": {
                    "receipt_id": receipt.pk,
                    "receipt_number": receipt.receipt_number,
                    "submitted_by": receipt.submitted_by_employee.display_name,
                    "submitted_at": receipt.submitted_at,
                    "line_count": receipt.created_line_count,
                }
            },
            status=201,
        )

    @extend_schema(
        responses={200: SampleInventoryReceiptDetailEnvelopeSerializer, 204: None}
    )
    @action(
        detail=False,
        methods=["get", "delete"],
        url_path=rf"receipts/(?P<receipt_id>{UUID_URL_REGEX})",
    )
    def receipt_detail(self, request, receipt_id=None):
        if request.method == "DELETE":
            delete_sample_inventory_receipt(
                receipt_id=receipt_id,
                actor_employee=self.actor_employee(),
            )
            return Response(status=204)
        receipt = get_object_or_404(sample_inventory_receipts_with_detail(), pk=receipt_id)
        return Response({"data": SampleInventoryReceiptDetailSerializer(receipt).data})
