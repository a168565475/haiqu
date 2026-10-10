from uuid import UUID

from django.core.exceptions import ValidationError as DjangoValidationError

from apps.reference_data.models import AccessoryMaterial, FabricMaterial

from .models import RawMaterialInformation


DIRECT_RAW_MATERIAL_SOURCE_KEYS = (
    "source_inventory_material_id",
    "source_raw_material_id",
    "source_cutting_material_id",
    "source_packaging_material_id",
)
REFERENCE_MAPPING_MODELS = {
    "source_fabric_material_id": FabricMaterial,
    "source_accessory_material_id": AccessoryMaterial,
}


def _cache_get(cache, key, loader):
    if cache is None:
        return loader()
    if key not in cache:
        cache[key] = loader()
    return cache[key]


def _uuid_values(values):
    normalized = set()
    for value in values:
        if not value:
            continue
        try:
            normalized.add(UUID(str(value)))
        except (TypeError, ValueError):
            continue
    return normalized


def lock_bom_line_material_identities(lines, *, extra_raw_material_ids=()):
    """按固定顺序锁住 BOM 行引用的映射与原料，避免校验后关联被并发替换。"""
    raw_ids = _uuid_values(extra_raw_material_ids)
    fabric_ids = set()
    accessory_ids = set()
    for line in lines:
        raw_values = getattr(line, "raw_values", None) or {}
        raw_ids.update(_uuid_values(raw_values.get(key) for key in DIRECT_RAW_MATERIAL_SOURCE_KEYS))
        fabric_ids.update(_uuid_values([raw_values.get("source_fabric_material_id")]))
        accessory_ids.update(_uuid_values([raw_values.get("source_accessory_material_id")]))

    locked_fabric_mappings = list(
        FabricMaterial.objects.select_for_update()
        .filter(pk__in=fabric_ids, archived_at__isnull=True)
        .order_by("pk")
    )
    locked_accessory_mappings = list(
        AccessoryMaterial.objects.select_for_update()
        .filter(pk__in=accessory_ids, archived_at__isnull=True)
        .order_by("pk")
    )
    raw_ids.update(
        item.inventory_raw_material_id
        for item in [*locked_fabric_mappings, *locked_accessory_mappings]
        if item.inventory_raw_material_id
    )
    list(
        RawMaterialInformation.objects.select_for_update()
        .filter(pk__in=raw_ids)
        .order_by("pk")
    )


def _active_inventory_material(material_id, *, require_material=False):
    try:
        queryset = RawMaterialInformation.objects.select_related("unit")
        queryset = queryset.filter(pk=material_id, archived_at__isnull=True)
        if require_material:
            queryset = queryset.filter(item_type="MATERIAL")
        return queryset.first()
    except (DjangoValidationError, TypeError, ValueError):
        return None


def _mapped_inventory_material(model, mapping_id):
    try:
        mapping_queryset = model.objects.all()
        mapping = mapping_queryset.filter(pk=mapping_id, archived_at__isnull=True).first()
    except (DjangoValidationError, TypeError, ValueError):
        return None
    if mapping is None or mapping.inventory_raw_material_id is None:
        return None
    return _active_inventory_material(mapping.inventory_raw_material_id, require_material=True)


def resolve_bom_line_raw_material(line, *, cache=None):
    """把 BOM 的来源编号解析为可记库存的原料；返回 (原料, 来源字段)。"""
    raw_values = getattr(line, "raw_values", None) or {}
    for source_key in DIRECT_RAW_MATERIAL_SOURCE_KEYS:
        source_id = raw_values.get(source_key)
        if not source_id:
            continue
        material = _cache_get(
            cache,
            ("raw", str(source_id)),
            lambda source_id=source_id: _active_inventory_material(source_id),
        )
        return material, source_key

    for source_key, model in REFERENCE_MAPPING_MODELS.items():
        source_id = raw_values.get(source_key)
        if not source_id:
            continue
        material = _cache_get(
            cache,
            (source_key, str(source_id)),
            lambda model=model, source_id=source_id: _mapped_inventory_material(model, source_id),
        )
        return material, source_key
    return None, None


def resolve_cutting_fabric_material(line, *, cache=None):
    """裁片产出身份与发出面料身份分离；缺资料时不按名称猜测。"""
    source = line.fabric_source_line
    if source is None or source.pk == line.pk or source.section.bom_id != line.section.bom_id:
        return None, "FABRIC_MAPPING_REQUIRED"
    if source.fabric_source_line_id or (source.raw_values or {}).get("source_cutting_material_id"):
        return None, "FABRIC_MAPPING_REQUIRED"
    material, _ = resolve_bom_line_raw_material(source, cache=cache)
    if (material is None or material.item_type != "MATERIAL"
            or material.category.category_name != "面料" or material.unit.unit_name != "米"):
        return None, "FABRIC_MAPPING_REQUIRED"
    return material, None
