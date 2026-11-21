from rest_framework import serializers
from drf_spectacular.utils import PolymorphicProxySerializer

from apps.procurement.api.read_details import ReadInboundSerializer

from ..models import PURCHASE_INBOUND_SECTION_NAMES
from ..purchase_receipt_records import RECEIPT_SOURCES, RECEIPT_STATUSES, UNASSIGNED_SECTION
from .serializers import ProcurementInboundProductSerializer


SECTION_NAMES = {**PURCHASE_INBOUND_SECTION_NAMES, UNASSIGNED_SECTION: '未登记'}


class PurchaseReceiptRecordQuerySerializer(serializers.Serializer):
    section = serializers.ChoiceField(choices=SECTION_NAMES, required=False)
    status = serializers.ChoiceField(choices=RECEIPT_STATUSES, required=False)
    q = serializers.CharField(max_length=200, allow_blank=True, default='')
    page = serializers.IntegerField(min_value=1, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=20)


class ReceiptRecordProductSerializer(ProcurementInboundProductSerializer):
    product_line_id = serializers.UUIDField(allow_null=True)


class PurchaseReceiptRecordSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    source = serializers.ChoiceField(choices=RECEIPT_SOURCES)
    production_task_number = serializers.CharField(allow_blank=True)
    inbound_number = serializers.CharField()
    purchase_order_number = serializers.CharField(allow_blank=True)
    material_section_display = serializers.SerializerMethodField()
    product_summary = ReceiptRecordProductSerializer(many=True)
    supplier_names = serializers.ListField(child=serializers.CharField())
    batch_number = serializers.IntegerField(allow_null=True)
    inbound_date = serializers.DateField()
    received_by_name = serializers.CharField()
    quality_confirmed_by_name = serializers.CharField(allow_blank=True)
    quality_confirmed_at = serializers.DateTimeField(allow_null=True)
    line_count = serializers.IntegerField()
    status = serializers.ChoiceField(source='record_status', choices=RECEIPT_STATUSES)
    can_quality_confirm = serializers.BooleanField()

    def get_material_section_display(self, record) -> str:
        return PURCHASE_INBOUND_SECTION_NAMES.get(record['material_section'], '未登记')


class PurchaseReceiptSectionSerializer(serializers.Serializer):
    id = serializers.ChoiceField(choices=SECTION_NAMES)
    name = serializers.CharField()


class PurchaseReceiptRecordsResponseSerializer(serializers.Serializer):
    data = PurchaseReceiptRecordSerializer(many=True)
    sections = PurchaseReceiptSectionSerializer(many=True)
    section = serializers.ChoiceField(choices=SECTION_NAMES, allow_blank=True)
    total = serializers.IntegerField()


class PurchaseReceiptRecordDetailSerializer(ReadInboundSerializer):
    purchase_order_id = serializers.UUIDField()
    status_display = serializers.SerializerMethodField()

    def get_status_display(self, instance) -> str:
        return RECEIPT_STATUSES[instance.record_status]

    class Meta(ReadInboundSerializer.Meta):
        fields = ReadInboundSerializer.Meta.fields + ['purchase_order_id']


class ReceiptRecordDetailQuerySerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=RECEIPT_SOURCES, default='PURCHASE')


class TransferReceiptRecordDetailSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    transfer_number = serializers.CharField()
    transfer_date = serializers.DateField()
    operated_by_name = serializers.CharField()
    remark = serializers.CharField()
    lines = serializers.ListField(child=serializers.DictField())


class PurchaseReceiptRecordResponseSerializer(serializers.Serializer):
    source = serializers.ChoiceField(choices=RECEIPT_SOURCES)
    data = PolymorphicProxySerializer(
        component_name='ReceiptRecordDetail', serializers=[PurchaseReceiptRecordDetailSerializer, TransferReceiptRecordDetailSerializer],
        resource_type_field_name=None,
    )
