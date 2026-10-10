"""根米收货和品质确认；不把未质检数量写成可用余额。"""
from decimal import Decimal
from rest_framework.exceptions import ValidationError
from apps.core.api.exceptions import Conflict
from apps.procurement.pipe_purchase import pipe_meters
from apps.products.models import RawMaterialInformation


def receipt_pipe_values(item, purchase_line=None, material=None):
    if purchase_line is not None:
        if purchase_line.section_type_snapshot != 'PROFILE':
            if item.get('received_bar_count') is not None or item.get('raw_bar_length_m') is not None:
                raise ValidationError({'items': '非管材不能提交管材根数。'})
            if purchase_line.purchase_order.source_type == 'SAMPLE':
                snapshot = purchase_line.calculation_snapshot
                material = RawMaterialInformation.objects.select_related('unit', 'category').filter(
                    pk=snapshot.get('raw_material_id'), item_type='MATERIAL', archived_at__isnull=True,
                    unit_id=snapshot.get('unit_id'), unit__status='ACTIVE', unit__archived_at__isnull=True,
                    category__status='ACTIVE', category__archived_at__isnull=True,
                ).exclude(category__category_name='管材').first()
                if material is None or purchase_line.source_unit_text not in {material.unit.unit_name, material.unit.unit_code}:
                    raise ValidationError({'items': '打样采购缺少有效原材料或单位来源，请重新核对采购来源。'})
                return {'raw_material_information': material, 'calculation_snapshot': snapshot}
            return {}
        if not purchase_line.raw_bar_length_m or not purchase_line.calculation_snapshot:
            raise Conflict('旧口径管材采购不能入库，请先补齐并重新确认根米采购。')
        length = purchase_line.raw_bar_length_m
        if item.get('raw_bar_length_m') is not None and item['raw_bar_length_m'] != length:
            raise ValidationError({'raw_bar_length_m': '实到单根长度与采购定制长度不同，不能按原长度入库。'})
        snapshot = purchase_line.calculation_snapshot
        material = RawMaterialInformation.objects.select_related('unit', 'category').filter(pk=snapshot.get('raw_material_id')).first()
    else:
        is_pipe = material is not None and material.item_type == 'MATERIAL' and material.category.category_name == '管材'
        if not is_pipe:
            if item.get('received_bar_count') is not None or item.get('raw_bar_length_m') is not None:
                raise ValidationError({'items': '非管材不能提交管材根数或长度。'})
            return {}
        length = item.get('raw_bar_length_m')
        snapshot = {'schema_version': 2, 'source': 'MANUAL', 'raw_material_id': str(material.pk)}
    if (material is None or material.archived_at or material.item_type != 'MATERIAL'
            or material.category.category_name != '管材' or material.unit.unit_name != '根'
            or material.unit.status != 'ACTIVE' or material.unit.archived_at
            or material.category.status != 'ACTIVE' or material.category.archived_at):
        raise ValidationError({'items': '管材入库缺少有效的根制原料身份。'})
    roots, meters = pipe_meters(item.get('received_bar_count'), length, field='received_bar_count')
    item['received_quantity'] = meters
    return {'measurement_kind': 'PIPE', 'raw_bar_length_m': length, 'received_bar_count': roots,
            'accepted_bar_count': roots, 'return_bar_count': 0,
            'calculation_snapshot': {**snapshot, 'received_bar_count': roots, 'received_meters': format(meters, '.2f')},
            'raw_material_information': material}


def quality_pipe_quantities(line, item):
    if line.measurement_kind != 'PIPE':
        if item.get('return_bar_count') is not None:
            raise ValidationError({'items': '非管材不能按根退货。'})
        if item.get('return_quantity') is None:
            raise ValidationError({'return_quantity': '请填写不良退货数量。'})
        return item['return_quantity']
    roots, meters = pipe_meters(item.get('return_bar_count'), line.raw_bar_length_m, field='return_bar_count', allow_zero=True)
    if roots > line.received_bar_count:
        raise ValidationError({'return_bar_count': '退货根数不能超过到货根数。'})
    line.return_bar_count = roots
    line.accepted_bar_count = line.received_bar_count - roots
    return meters
