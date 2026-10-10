"""与 BOM 共用生产维护资料，仅向打样编辑器提供用料字段。"""
from django.db.models import Q, Prefetch
from apps.products.models import RawMaterialInformation
from apps.reference_data import models as ref

ACTIVE = {'status': 'ACTIVE', 'archived_at__isnull': True}


def color_label(color):
    return ' - '.join(value for value in [color.color_name, color.color_card, color.color_code] if value)


def material_reference_options():
    def options(model, field):
        return [{'label': getattr(row, field), 'pinyin_search': getattr(row, 'pinyin_search', '')} for row in model.objects.filter(**ACTIVE)]
    accessories = ref.AccessoryProductName.objects.filter(**ACTIVE).prefetch_related(
        Prefetch('specifications', queryset=ref.AccessorySpecification.objects.filter(**ACTIVE)),
        Prefetch('colors', queryset=ref.AccessoryColor.objects.filter(**ACTIVE)),
    )
    catalog_names = {category: list(material_candidates(category, '').values_list('material_name', flat=True).order_by('material_name').distinct()) for category in ['hardware', 'plastic', 'packaging']}
    return {
        **{category: {'material': [{'label': value} for value in material_candidates(category, '').exclude(material='').values_list('material', flat=True).order_by('material').distinct()]} for category in ['hardware', 'plastic', 'packaging']},
        'catalogNames': catalog_names,
        'colors': [{'label': color_label(row)} for row in ref.ProductColor.objects.filter(**ACTIVE)],
        'tubeDiameters': options(ref.TubeDiameter, 'diameter_value'),
        'tubeThicknesses': options(ref.TubeThickness, 'thickness_value'),
        'tube': {'name': options(ref.TubeProductName, 'product_name'), 'material': options(ref.TubeMaterial, 'material_name'), 'color': options(ref.TubeCoatingColor, 'color_name')},
        'fabric': {'material': options(ref.FabricMaterial, 'material_name'), 'specification': options(ref.FabricSpecification, 'specification_name'), 'color': options(ref.ProductColor, 'color_name')},
        'accessory': {'material': options(ref.AccessoryMaterial, 'material_name')},
        'accessories': [{'id': str(row.pk), 'label': row.product_name, 'unitLabel': row.unit_name,
                         'specifications': [{'label': item.specification_value} for item in row.specifications.all()],
                         'colors': [{'label': item.color_name} for item in row.colors.all()]} for row in accessories],
    }


def material_candidates(category, keyword, name=''):
    categories = {'tube': '管材', 'hardware': '五金', 'plastic': '塑料件', 'accessory': '辅料', 'fabric': '面料', 'packaging': '包材'}
    queryset = RawMaterialInformation.objects.filter(
        item_type='MATERIAL', category__item_type='MATERIAL', category__category_name=categories[category],
        category__status='ACTIVE', category__archived_at__isnull=True, archived_at__isnull=True,
        unit__status='ACTIVE', unit__archived_at__isnull=True,
    ).select_related('unit', 'color').order_by('material_number', 'id')
    if category == 'tube':
        queryset = queryset.filter(unit__unit_name='根')
    if keyword:
        queryset = queryset.filter(Q(material_number__icontains=keyword) | Q(material_name__icontains=keyword) | Q(specification__icontains=keyword) | Q(material__icontains=keyword) | Q(color__color_name__icontains=keyword) | Q(color_snapshot__icontains=keyword))
    if name:
        queryset = queryset.filter(material_name=name)
    return queryset
