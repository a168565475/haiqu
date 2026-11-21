"""采购只读详情；不推进采购、入库或退货状态。"""
from decimal import Decimal

from django.db.models import Exists, OuterRef, Prefetch
from drf_spectacular.utils import extend_schema_field
from rest_framework import serializers

from apps.inventory.models import MaterialInbound, MaterialInboundLine, MaterialInboundStatus
from apps.inventory.purchase_receiving_sections import receiving_lines_in_scope
from ..group_selectors import purchase_batch_display_status
from ..catalog_materials import is_weight_purchase
from ..models import PurchaseOrderStatus, PurchaseReturn, PurchaseReturnLine
from .serializers import PurchaseOrderDetailSerializer, PurchaseOrderLineSerializer
from .return_views import PurchaseReturnSerializer


def with_read_detail_records(queryset, *, receiving_sections=None):
    inbound_lines = MaterialInboundLine.objects.select_related("zone__warehouse", "location")
    inbound_lines = receiving_lines_in_scope(inbound_lines, receiving_sections, order_field="inbound__purchase_order")
    inbounds = MaterialInbound.objects.select_related(
        "received_by_employee", "quality_confirmed_by_employee",
    ).prefetch_related(Prefetch("lines", queryset=inbound_lines))
    return_lines = PurchaseReturnLine.objects.select_related("inbound_line__purchase_order_line")
    if receiving_sections is not None:
        inbounds = inbounds.filter(Exists(inbound_lines.filter(inbound_id=OuterRef("pk"))))
        return_lines = return_lines.filter(inbound_line__in=inbound_lines)
    returns = PurchaseReturn.objects.select_related(
        "purchase_order", "inbound", "generated_by_employee", "confirmed_by_employee", "completed_by_employee",
    ).prefetch_related(Prefetch("lines", queryset=return_lines))
    if receiving_sections is not None:
        returns = returns.filter(Exists(return_lines.filter(return_order_id=OuterRef("pk"))))
    return queryset.select_related("completed_by_employee").prefetch_related(
        Prefetch("material_inbounds", queryset=inbounds), Prefetch("returns", queryset=returns),
    )


class ReadDetailLineSerializer(PurchaseOrderLineSerializer):
    received_quantity = serializers.SerializerMethodField()
    accepted_quantity = serializers.SerializerMethodField()
    return_quantity = serializers.SerializerMethodField()
    received_bar_count = serializers.SerializerMethodField()
    accepted_bar_count = serializers.SerializerMethodField()
    return_bar_count = serializers.SerializerMethodField()
    received_weight_kg = serializers.SerializerMethodField()
    accepted_weight_kg = serializers.SerializerMethodField()
    return_weight_kg = serializers.SerializerMethodField()

    class Meta(PurchaseOrderLineSerializer.Meta):
        fields = PurchaseOrderLineSerializer.Meta.fields + ["received_quantity", "accepted_quantity", "return_quantity",
                                                          "received_bar_count", "accepted_bar_count", "return_bar_count"]
        fields = fields + ["received_weight_kg", "accepted_weight_kg", "return_weight_kg"]

    @staticmethod
    def _quantity(line, field, confirmed_only=False):
        if is_weight_purchase(line):
            return ReadDetailLineSerializer._weight(line, field.replace("_quantity", "_weight_kg"), confirmed_only)
        return str(sum((getattr(record, field) for record in line.material_inbound_lines.all()
                        if not confirmed_only or record.inbound.status == MaterialInboundStatus.CONFIRMED), Decimal("0")))

    def get_received_quantity(self, line):
        return self._quantity(line, "received_quantity")

    def get_accepted_quantity(self, line):
        return self._quantity(line, "accepted_quantity", confirmed_only=True)

    def get_return_quantity(self, line):
        return self._quantity(line, "return_quantity", confirmed_only=True)

    @staticmethod
    def _weight(line, field, confirmed_only=False):
        records = [record for record in line.material_inbound_lines.all()
                   if not confirmed_only or record.inbound.status == MaterialInboundStatus.CONFIRMED]
        if line.source_unit_text != "KG" and not any(getattr(record, field) is not None for record in records):
            return None
        values = [getattr(record, field) for record in records]
        if any(value is None or not value.is_finite() or value < 0 for value in values):
            return None
        return str(sum(values, Decimal("0")))

    def get_received_weight_kg(self, line):
        return self._weight(line, "received_weight_kg")

    def get_accepted_weight_kg(self, line):
        return self._weight(line, "accepted_weight_kg", confirmed_only=True)

    def get_return_weight_kg(self, line):
        return self._weight(line, "return_weight_kg", confirmed_only=True)

    @staticmethod
    def _bar_count(line, field, confirmed_only=False):
        if not line.raw_bar_length_m:
            return None
        records = [record for record in line.material_inbound_lines.all()
                   if not confirmed_only or record.inbound.status == MaterialInboundStatus.CONFIRMED]
        # 只汇总已保存的根数，旧记录缺少换算来源时不把米数冒充根数。
        if any(record.measurement_kind != "PIPE" or record.raw_bar_length_m != line.raw_bar_length_m
               or getattr(record, field) is None for record in records):
            return None
        return sum(getattr(record, field) for record in records)

    def get_received_bar_count(self, line) -> int | None:
        return self._bar_count(line, "received_bar_count")

    def get_accepted_bar_count(self, line) -> int | None:
        return self._bar_count(line, "accepted_bar_count", confirmed_only=True)

    def get_return_bar_count(self, line) -> int | None:
        return self._bar_count(line, "return_bar_count", confirmed_only=True)


class ReadInboundLineSerializer(serializers.ModelSerializer):
    warehouse_name = serializers.CharField(source="zone.warehouse.warehouse_name", read_only=True)
    zone_name = serializers.CharField(source="zone.zone_name", read_only=True)
    location_number = serializers.CharField(source="location.location_number", read_only=True, default="")
    measurement_kind = serializers.SerializerMethodField()
    piece_unit = serializers.SerializerMethodField()
    received_piece_count = serializers.SerializerMethodField()
    accepted_piece_count = serializers.SerializerMethodField()
    return_piece_count = serializers.SerializerMethodField()

    def get_measurement_kind(self, line) -> str:
        from apps.inventory.hardware_receipts import is_hardware_weight
        return "HARDWARE_WEIGHT" if is_hardware_weight(line) else line.measurement_kind

    def get_piece_unit(self, line) -> str:
        from apps.inventory.hardware_receipts import is_hardware_weight
        return (line.calculation_snapshot or {}).get("piece_unit", "") if is_hardware_weight(line) else ""

    @staticmethod
    def _piece_count(line, field):
        from apps.inventory.hardware_receipts import is_hardware_weight
        value = getattr(line, field)
        return str(value) if is_hardware_weight(line) and value is not None else None

    def get_received_piece_count(self, line) -> str | None:
        return self._piece_count(line, "received_quantity")

    def get_accepted_piece_count(self, line) -> str | None:
        return self._piece_count(line, "accepted_quantity")

    def get_return_piece_count(self, line) -> str | None:
        return self._piece_count(line, "return_quantity")

    class Meta:
        model = MaterialInboundLine
        fields = ["id", "purchase_order_line_id", "part_name_snapshot", "specification_snapshot",
                  "material_snapshot", "supplier_name_snapshot", "source_unit_text_snapshot",
                  "material_attributes_snapshot", "material_catalog_id", "material_selection_snapshot",
                  "section_type_snapshot", "section_title_snapshot", "calculation_snapshot",
                  "received_quantity", "accepted_quantity", "return_quantity", "quality_remark",
                  "warehouse_name", "zone_name", "location_number", "measurement_kind", "received_bar_count",
                  "accepted_bar_count", "return_bar_count", "raw_bar_length_m", "bar_weight_kg",
                  "received_weight_kg", "accepted_weight_kg", "return_weight_kg"]
        fields += ["piece_unit", "received_piece_count", "accepted_piece_count", "return_piece_count"]
        read_only_fields = fields


class ReadInboundSerializer(serializers.ModelSerializer):
    status_display = serializers.CharField(source="get_status_display", read_only=True)
    material_section_display = serializers.CharField(read_only=True)
    received_by_name = serializers.CharField(source="received_by_employee.display_name", read_only=True)
    quality_confirmed_by_name = serializers.CharField(source="quality_confirmed_by_employee.display_name", read_only=True, default="")
    lines = ReadInboundLineSerializer(many=True, read_only=True)

    class Meta:
        model = MaterialInbound
        fields = ["id", "inbound_number", "inbound_date", "status", "status_display", "remark",
                  "material_section", "material_section_display",
                  "received_by_name", "quality_confirmed_by_name", "quality_confirmed_at", "created_at", "lines"]
        read_only_fields = fields


class PurchaseOrderReadDetailSerializer(PurchaseOrderDetailSerializer):
    display_status = serializers.SerializerMethodField()
    lines = ReadDetailLineSerializer(many=True, read_only=True)
    completed_by_name = serializers.CharField(source="completed_by_employee.display_name", read_only=True, default="")
    inbounds = ReadInboundSerializer(source="material_inbounds", many=True, read_only=True)
    returns = PurchaseReturnSerializer(many=True, read_only=True)

    class Meta(PurchaseOrderDetailSerializer.Meta):
        fields = PurchaseOrderDetailSerializer.Meta.fields + ["display_status", "completed_by_name", "inbounds", "returns"]

    @extend_schema_field(serializers.ChoiceField(choices=PurchaseOrderStatus.choices))
    def get_display_status(self, instance):
        return purchase_batch_display_status(instance)
