from drf_spectacular.utils import extend_schema
from rest_framework import serializers
from rest_framework.exceptions import PermissionDenied
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.api.permissions import HasActiveEmployee

from ..material_stock_records import MOVEMENT_LABELS, material_stock_record_page
from ..models import LEGACY_PACKAGING_RECEIPT_NAME, PURCHASE_INBOUND_SECTION_NAMES
from ..purchase_receipt_records import RECEIPT_PERMISSIONS, receipt_record_permissions
from ..purchase_receiving_sections import MATERIAL_SECTIONS, OTHER_SECTION


SECTION_LABELS = {**MATERIAL_SECTIONS, OTHER_SECTION: "其他材料"}


class MaterialStockRecordQuery(serializers.Serializer):
    direction = serializers.ChoiceField(choices=("IN", "OUT"))
    section = serializers.ChoiceField(choices=SECTION_LABELS, default="TUBE")
    task_number = serializers.CharField(max_length=50, allow_blank=True, default="")
    q = serializers.CharField(max_length=200, allow_blank=True, default="")
    start_date = serializers.DateField(required=False)
    end_date = serializers.DateField(required=False)
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)

    def validate(self, values):
        if "start_date" in values and "end_date" in values and values["start_date"] > values["end_date"]:
            raise serializers.ValidationError({"end_date": "结束日期不能早于开始日期。"})
        return values


class MaterialStockRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    source_type = serializers.CharField()
    origin_id = serializers.UUIDField()
    business_date = serializers.DateField()
    task_number = serializers.CharField()
    voucher_number = serializers.CharField()
    movement_label = serializers.SerializerMethodField()
    origin_section_display = serializers.SerializerMethodField()
    item_name = serializers.CharField()
    specification = serializers.CharField()
    color = serializers.CharField()
    actual_quantity = serializers.CharField()
    stock_unit = serializers.CharField()
    warehouse_name = serializers.CharField()
    zone_name = serializers.CharField()
    actor_name = serializers.CharField()
    recipient_name = serializers.CharField()
    counterparty = serializers.CharField()
    note = serializers.CharField()

    def get_movement_label(self, row) -> str:
        return MOVEMENT_LABELS[row["record_kind"]]

    def get_origin_section_display(self, row) -> str:
        if row["legacy_packaging"]:
            return LEGACY_PACKAGING_RECEIPT_NAME
        return PURCHASE_INBOUND_SECTION_NAMES.get(row["origin_section"], "")


class MaterialStockRecordResponse(serializers.Serializer):
    data = MaterialStockRecordSerializer(many=True)
    total = serializers.IntegerField()
    show_other = serializers.BooleanField()


class MaterialStockRecordsView(APIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(parameters=[MaterialStockRecordQuery], responses=MaterialStockRecordResponse)
    def get(self, request):
        query = MaterialStockRecordQuery(data=request.query_params)
        query.is_valid(raise_exception=True)
        filters = query.validated_data
        allowed = receipt_record_permissions(request)
        if filters["direction"] == "OUT" and RECEIPT_PERMISSIONS[2] not in allowed:
            raise PermissionDenied("当前账号没有查看材料出库记录的权限。")
        rows, total, show_other = material_stock_record_page(request, filters, allowed)
        return Response({"data": MaterialStockRecordSerializer(rows, many=True).data, "total": total, "show_other": show_other})
