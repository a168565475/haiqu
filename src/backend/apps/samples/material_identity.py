"""打样非管材沿用原单位，但必须冻结所选库存原料编号。"""
from django.core.exceptions import ValidationError as DjangoValidationError
from rest_framework.exceptions import ValidationError
from apps.products.models import RawMaterialInformation

CATEGORIES = {'hardware': '五金', 'plastic': '塑料件', 'accessory': '辅料', 'fabric': '面料', 'packaging': '包材'}


def sample_material_snapshot(procurement, row):
    try:
        material = RawMaterialInformation.objects.select_related('unit').filter(
            pk=row.get('rawMaterialId'), item_type='MATERIAL', archived_at__isnull=True,
            category__category_name=CATEGORIES.get(row.get('category')), category__status='ACTIVE',
            category__archived_at__isnull=True, unit__status='ACTIVE', unit__archived_at__isnull=True,
        ).first()
    except (ValueError, TypeError, DjangoValidationError):
        material = None
    if material is None:
        raise ValidationError({'rawMaterialId': '请在打样用料中选择对应分类的库存原材料，不能按名称猜测关联。'})
    if (row.get('name'), row.get('specification'), row.get('material')) != (
            material.material_name, material.specification, material.material):
        raise ValidationError({'lines': '打样材料名称、规格、材质与所选库存原料不一致。'})
    if row.get('unitLabel') not in {material.unit.unit_name, material.unit.unit_code}:
        raise ValidationError({'lines': '打样需求单位与所选原料库存单位不一致。'})
    return {'schema_version': 2, 'source': 'SAMPLE', 'raw_material_id': str(material.pk),
            'unit_id': str(material.unit_id), 'sample_procurement_request_id': str(procurement.pk),
            'sample_line_key': str(row['key'])}
