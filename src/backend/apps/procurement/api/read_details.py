"""采购只读详情；不推进采购、入库或退货状态。"""
from decimal import Decimal

from django.db.models import Prefetch
from rest_framework import serializers

from apps.inventory.models import MaterialInbound, MaterialInboundLine, MaterialInboundStatus
from ..models import PurchaseReturn, PurchaseReturnLine
from .serializers import PurchaseOrderDetailSerializer, PurchaseOrderLineSerializer
from .return_views import PurchaseReturnSerializer


def with_read_detail_records(queryset):
    inbound_lines = MaterialInboundLine.objects.select_related("zone__warehouse", "location")
    inbounds = MaterialInbound.objects.select_related(
        "received_by_employee", "quality_confirmed_by_employee",
    ).prefetch_related(Prefetch("lines", queryset=inbound_lines))
    returns = PurchaseReturn.objects.select_related(
        "purchase_order", "inbound", "generated_by_employee", "confirmed_by_employee", "completed_by_employee",
    ).prefetch_related(Prefetch("lines", queryset=PurchaseReturnLine.objects.select_related(
        "inbound_line__purchase_order_line",
    )))
    return queryset.select_related("completed_by_employee").prefetch_related(
        Prefetch("material_inbounds", queryset=inbounds), Prefetch("returns", queryset=returns),
    )


class ReadDetailLineSerializer(PurchaseOrderLineSerializer):
    received_quantity = serializers.SerializerMethodField()
    accepted_quantity = serializers.SerializerMethodField()
    return_quantity = serializers.SerializerMethodField()

    class Meta(PurchaseOrderLineSerializer.Meta):
        fields = PurchaseOrderLineSerializer.Meta.fields + ["received_quantity", "accepted_quantity", "return_quantity"]

    @staticmethod
    def _quantity(line, field, confirmed_only=False):
        return str(sum((getattr(record, field) for record in line.material_inbound_lines.all()
                        if not confirmed_only or record.inbound.status == MaterialInboundStatus.CONFIRMED), Decimal("0")))

    def get_received_quantity(self, line):
        return self._quantity(line, "received_quantity")

    def get_accepted_quantity(self, line):
        return self._quantity(line, "accepted_quantity", confirmed_only=True)

    def get_return_quantity(self, line):
        return self._quantity(line, "return_quantity", confirmed_only=True)


class ReadInboundLineSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="zone.warehouse.warehouse_name", read_only=True)
    zone_name = serializers.CharField(source="zone.zone_name", read_only=True)
    location_number = serializers.CharField(source="location.location_number", read_only=True, default="")

    class Meta:
        model = MaterialInboundLine
        fields = ["id", "purchase_order_line_id", "part_name_snapshot", "specification_snapshot",
                  "material_snapshot", "supplier_name_snapshot", "source_unit_text_snapshot",
                  "material_attributes_snapshot",
                  "received_quantity", "accepted_quantity", "return_quantity", "quality_remark",
                  "warehouse_name", "zone_name", "location_number", "received_bar_count",
                  "accepted_bar_count", "return_bar_count", "raw_bar_length_m"]
        read_only_fields = fields


class ReadInboundSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    received_by_name = serializers.CharField(source="received_by_employee.display_name", read_only=True)
    quality_confirmed_by_name = serializers.CharField(source="quality_confirmed_by_employee.display_name", read_only=True, default="")
    lines = ReadInboundLineSerializer(many=True, read_only=True)

    class Meta:
        model = MaterialInbound
        fields = ["id", "inbound_number", "inbound_date", "status", "status_display", "remark",
                  "received_by_name", "quality_confirmed_by_name", "quality_confirmed_at", "created_at", "lines"]
        read_only_fields = fields


class PurchaseOrderReadDetailSerializer(PurchaseOrderDetailSerializer):
    lines = ReadDetailLineSerializer(many=True, read_only=True)
    completed_by_name = serializers.CharField(source="completed_by_employee.display_name", read_only=True, default="")
    inbounds = ReadInboundSerializer(source="material_inbounds", many=True, read_only=True)
    returns = PurchaseReturnSerializer(many=True, read_only=True)

    class Meta(PurchaseOrderDetailSerializer.Meta):
        fields = PurchaseOrderDetailSerializer.Meta.fields + ["completed_by_name", "inbounds", "returns"]
