"""D2只接受图稿中可填写字段，数量和换算由服务端复核。"""
import re
from decimal import Decimal

from rest_framework import serializers
from drf_spectacular.utils import extend_schema_field

from ..models import TubeSourceKind
from ..tube_kinds import CUTTING_SOURCES


@extend_schema_field({'oneOf': [{'type': 'integer', 'minimum': 0, 'maximum': 99999999999999},
    {'type': 'string', 'pattern': r'^\s*[0-9]*\s*$'}], 'nullable': True,
    'description': '整数加工数量（支或套）；空白或null按0，不接受负数、小数或布尔值。'})
class TubeQuantityField(serializers.Field):
    def to_internal_value(self, data):
        if data is None or (isinstance(data, str) and not data.strip()):
            return 0
        text = str(data).strip()
        if isinstance(data, bool) or not re.fullmatch(r'[0-9]+', text):
            raise serializers.ValidationError('请填写整数数量，不支持负数、小数或文字。')
        significant = text.lstrip('0') or '0'
        if len(significant) > 14:
            raise serializers.ValidationError('数量超出可保存范围。')
        return int(significant)

    def to_representation(self, value):
        return str(value)


class TubeSourceQuerySerializer(serializers.Serializer):
    schedule_product_id = serializers.UUIDField()
    source_kind = serializers.ChoiceField(choices=TubeSourceKind.choices)
    zone_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    craft_id = serializers.UUIDField(required=False)

    def validate(self, attrs):
        if attrs['source_kind'] in CUTTING_SOURCES and not attrs.get('craft_id'):
            raise serializers.ValidationError({'craft_id': '裁片外发请选择刺绣、丝印、裁剪或车缝工艺。'})
        return attrs


class TubeLineWriteSerializer(serializers.Serializer):
    component_identity = serializers.UUIDField()
    quantity = TubeQuantityField(allow_null=True)
    factory_id = serializers.UUIDField(required=False, allow_null=True)
    unit_price = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal('0'),
                                         required=False, allow_null=True)

    def to_internal_value(self, data):
        price = data.get('unit_price') if isinstance(data, dict) else None
        if isinstance(price, str) and not price.strip():
            raise serializers.ValidationError({'unit_price': '加工单价不能为空字符串。'})
        return super().to_internal_value(data)

    def validate_unit_price(self, value):
        if value is not None and value != value.quantize(Decimal('0.01')):
            raise serializers.ValidationError('加工单价最多保留两位小数。')
        return value.quantize(Decimal('0.01')) if value is not None else None

    def validate(self, attrs):
        attrs['quantity'] = attrs.get('quantity') or 0
        if attrs['quantity'] > 0 and not attrs.get('factory_id'):
            raise serializers.ValidationError({'factory_id': '正数办理行必须选择一家加工厂。'})
        return attrs


class TubeMaterialWriteSerializer(serializers.Serializer):
    bom_line_id = serializers.UUIDField()
    factory_id = serializers.UUIDField()
    quantity = serializers.DecimalField(max_digits=18, decimal_places=4, min_value=Decimal('0.0001'))
    zone_id = serializers.UUIDField()

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError('随单材料只能填写BOM材料、加工厂、数量和来源库区。')
        return super().to_internal_value(data)


class TubeOrderWriteSerializer(TubeSourceQuerySerializer):
    client_request_id = serializers.UUIDField()
    source_revision = serializers.CharField(min_length=64, max_length=64)
    planned_dispatch_date = serializers.DateField()
    expected_return_date = serializers.DateField()
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000, default='')
    lines = TubeLineWriteSerializer(many=True, allow_empty=False)
    materials = TubeMaterialWriteSerializer(many=True, required=False)
    material_source_revision = serializers.CharField(min_length=64, max_length=64, required=False)

    def validate(self, attrs):
        attrs = super().validate(attrs)
        if attrs['expected_return_date'] < attrs['planned_dispatch_date']:
            raise serializers.ValidationError({'expected_return_date': '预计回货日期不能早于计划发出日期。'})
        materials = attrs.get('materials', [])
        if materials and not attrs.get('material_source_revision'):
            raise serializers.ValidationError({'material_source_revision': '请选择并刷新随单材料来源。'})
        # 保持旧无五金请求的幂等摘要，空数组不改变既有保存内容。
        if not materials:
            attrs.pop('materials', None)
            attrs.pop('material_source_revision', None)
        return attrs

    def validate_materials(self, rows):
        if len(rows) > 500:
            raise serializers.ValidationError('一次最多提交500项随单材料。')
        keys = [(row['bom_line_id'], row['factory_id'], row['zone_id']) for row in rows]
        if len(keys) != len(set(keys)):
            raise serializers.ValidationError('同一材料、加工厂和来源库区不能重复添加。')
        return sorted(rows, key=lambda row: (str(row['bom_line_id']), str(row['factory_id']), str(row['zone_id'])))

    def validate_lines(self, rows):
        if len(rows) > 500:
            raise serializers.ValidationError('一次最多提交500个加工部位。')
        identities = [row['component_identity'] for row in rows]
        if len(set(identities)) != len(identities):
            raise serializers.ValidationError('同一BOM部位不能重复添加或拆给多家加工厂。')
        rows = [row for row in rows if row['quantity'] > 0]
        if not rows:
            raise serializers.ValidationError('请至少填写一项大于0的外发数量。')
        return sorted(rows, key=lambda row: str(row['component_identity']))


class TubeActionWriteSerializer(serializers.Serializer):
    client_request_id = serializers.UUIDField()

    def to_internal_value(self, data):
        if not isinstance(data, dict):
            raise serializers.ValidationError('外发操作必须提交有效的字段对象。')
        unknown = set(data) - set(self.fields)
        if unknown:
            raise serializers.ValidationError({'detail': '本次仅办理整单原保存数量，不接受数量、厂家或库区修改。'})
        return super().to_internal_value(data)


class TubeDispatchWriteSerializer(TubeActionWriteSerializer):
    actual_dispatch_date = serializers.DateField()


class TubeCancelWriteSerializer(TubeActionWriteSerializer):
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000, default='')


class TubeReceiptCandidatesQuerySerializer(serializers.Serializer):
    category = serializers.ChoiceField(choices=['tube', 'cutting'], required=False, default='tube')
    search = serializers.CharField(required=False, allow_blank=True, max_length=200, default='')
    source_kind = serializers.ChoiceField(choices=TubeSourceKind.choices, required=False)
    page = serializers.IntegerField(min_value=1, max_value=1000000, default=1)
    page_size = serializers.IntegerField(min_value=1, max_value=100, default=50)


class TubeReceiptLineWriteSerializer(serializers.Serializer):
    order_line_id = serializers.UUIDField()
    received_quantity = TubeQuantityField(allow_null=True)
    shortage_reason = serializers.CharField(required=False, allow_blank=True, max_length=2000, default='')
    zone_id = serializers.UUIDField(required=False, allow_null=True, default=None)

    def to_internal_value(self, data):
        if not isinstance(data, dict) or set(data) - set(self.fields):
            raise serializers.ValidationError('回货行只能填写原明细、实收数量、差额原因和库区。')
        return super().to_internal_value(data)

    def validate(self, attrs):
        # DRF的allow_null在字段转换前返回None，必须在行级归一为空白0。
        attrs['received_quantity'] = attrs.get('received_quantity') or 0
        return attrs


class TubeReceiptWriteSerializer(TubeActionWriteSerializer):
    receipt_date = serializers.DateField()
    warehouse_id = serializers.UUIDField(required=False, allow_null=True, default=None)
    remark = serializers.CharField(required=False, allow_blank=True, max_length=2000, default='')
    lines = TubeReceiptLineWriteSerializer(many=True, allow_empty=False)

    def validate_lines(self, rows):
        if len(rows) > 500:
            raise serializers.ValidationError('一单最多登记500个原加工部位。')
        identifiers = [row['order_line_id'] for row in rows]
        if len(set(identifiers)) != len(identifiers):
            raise serializers.ValidationError('同一原加工明细只能登记一次。')
        return sorted(rows, key=lambda row: str(row['order_line_id']))

    def validate(self, attrs):
        positive = any(row['received_quantity'] > 0 for row in attrs['lines'])
        if positive and not attrs.get('warehouse_id'):
            raise serializers.ValidationError({'warehouse_id': '有实收半成品时必须选择入库仓库。'})
        # 全零及零行没有入账位置，不接受或记录它们的过期库区值。
        if not positive:
            attrs['warehouse_id'] = None
        for row in attrs['lines']:
            if row['received_quantity'] == 0:
                row['zone_id'] = None
            elif not row.get('zone_id'):
                raise serializers.ValidationError({'lines': '每个正数实收部位必须选择所属仓库的库区。'})
        return attrs


class TubeReceiptResultLineSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_line_id = serializers.UUIDField()
    component_identity = serializers.UUIDField()
    part_name = serializers.CharField()
    material = serializers.CharField()
    specification = serializers.CharField()
    unit = serializers.CharField(allow_null=True)
    pieces_per_set = serializers.IntegerField(allow_null=True)
    fabric_material = serializers.CharField(allow_null=True)
    fabric_specification = serializers.CharField(allow_null=True)
    fabric_color = serializers.CharField(allow_null=True)
    completed_craft_name = serializers.CharField(allow_null=True)
    thickness = serializers.CharField(allow_null=True)
    cutting_length_mm = serializers.CharField(allow_null=True)
    raw_color = serializers.CharField(allow_null=True)
    spray_color = serializers.CharField(allow_null=True)
    factory_id = serializers.UUIDField()
    factory_name = serializers.CharField()
    unit_price = serializers.CharField(allow_null=True)
    planned_amount = serializers.CharField(allow_null=True)
    dispatched_quantity = serializers.CharField()
    received_quantity = serializers.CharField()
    shortage_quantity = serializers.CharField()
    shortage_reason = serializers.CharField(allow_blank=True)
    zone_id = serializers.UUIDField(allow_null=True)
    zone_name = serializers.CharField(allow_blank=True)
    stock_movement_id = serializers.UUIDField(allow_null=True)


class TubeReceiptResultSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    receipt_number = serializers.CharField()
    order_id = serializers.UUIDField()
    order_number = serializers.CharField()
    status = serializers.ChoiceField(choices=['COMPLETED'])
    source_kind = serializers.ChoiceField(choices=TubeSourceKind.choices)
    source_label = serializers.CharField()
    category = serializers.ChoiceField(choices=['tube', 'cutting'])
    output_unit = serializers.CharField()
    craft_id = serializers.UUIDField()
    craft_name = serializers.CharField()
    client_request_id = serializers.UUIDField()
    receipt_date = serializers.DateField()
    warehouse_id = serializers.UUIDField(allow_null=True)
    warehouse_name = serializers.CharField(allow_blank=True)
    confirmed_at = serializers.DateTimeField()
    actor_name = serializers.CharField()
    remark = serializers.CharField(allow_blank=True)
    total_dispatched_quantity = serializers.CharField()
    total_received_quantity = serializers.CharField()
    total_shortage_quantity = serializers.CharField()
    planned_amount = serializers.CharField(allow_null=True)
    etag = serializers.CharField()
    created = serializers.BooleanField()
    lines = TubeReceiptResultLineSerializer(many=True)


class TubeReceiptResponseSerializer(serializers.Serializer):
    data = TubeReceiptResultSerializer()


class TubeReceiptZoneSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    warehouse_id = serializers.UUIDField()
    warehouse = serializers.CharField()
    name = serializers.CharField()


class TubeReceiptWarehouseSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    name = serializers.CharField()


class TubeReceiptPreviewSerializer(serializers.Serializer):
    order = serializers.JSONField()
    etag = serializers.CharField()
    can_receive = serializers.BooleanField()
    blockers = serializers.ListField(child=serializers.CharField())
    actor_name = serializers.CharField()
    today = serializers.DateField()
    warehouses = TubeReceiptWarehouseSerializer(many=True)
    zones = TubeReceiptZoneSerializer(many=True)
    receipt = TubeReceiptResultSerializer(allow_null=True)


class TubeReceiptPreviewResponseSerializer(serializers.Serializer):
    data = TubeReceiptPreviewSerializer()


class TubeReceiptCandidateSerializer(serializers.Serializer):
    id = serializers.UUIDField()
    order_number = serializers.CharField()
    task_number = serializers.CharField()
    task_order_number = serializers.CharField()
    product_number = serializers.CharField()
    item_number = serializers.CharField()
    product_name = serializers.CharField()
    color = serializers.CharField()
    source_kind = serializers.ChoiceField(choices=TubeSourceKind.choices)
    source_label = serializers.CharField()
    category = serializers.ChoiceField(choices=['tube', 'cutting'])
    output_unit = serializers.CharField()
    craft_id = serializers.UUIDField()
    craft_name = serializers.CharField()
    actual_dispatch_date = serializers.DateField()
    expected_return_date = serializers.DateField()
    total_quantity = serializers.CharField()
    factory_names = serializers.ListField(child=serializers.CharField())


class TubeReceiptCandidatesSerializer(serializers.Serializer):
    items = TubeReceiptCandidateSerializer(many=True)
    total = serializers.IntegerField()
    page = serializers.IntegerField()
    page_size = serializers.IntegerField()


class TubeReceiptCandidatesResponseSerializer(serializers.Serializer):
    data = TubeReceiptCandidatesSerializer()
