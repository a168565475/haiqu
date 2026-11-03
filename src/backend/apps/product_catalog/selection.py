"""业务单据选择产品时固化属性；已保存的选择不跟随主档重算。"""

from copy import deepcopy

from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework import serializers
from rest_framework.exceptions import ValidationError

from apps.reference_data.models import ProductionUnit

from .api.serializers import ProductSelectionSerializer
from .models import ProductCatalog, ProductCatalogCategory, ProductCatalogName


def is_product_entry_snapshot(snapshot):
    return isinstance(snapshot, dict) and snapshot.get("entry_state") == "draft" and isinstance(snapshot.get("entry_draft"), dict)


def _draft_error(field, message):
    raise ValidationError({"product_selection": {"draft": {field: message}}})


def _resolve_draft(catalog_id, selected, existing_snapshot):
    """前序单据仅校验和固化输入；这里不创建或更新任何产品维护记录。"""
    draft = deepcopy(selected["draft"])
    sources = draft["sources"]
    product = None
    if catalog_id:
        catalog_id = serializers.UUIDField().run_validation(catalog_id)
        product = ProductCatalog.objects.select_related("name__category").filter(pk=catalog_id).first()
        if product is None or product.archived_at or product.name.archived_at or product.name.category.archived_at:
            _draft_error("name", "所选产品不存在或已停用，请重新选择。")
        version = selected.get("catalog_version")
        if not version or parse_datetime(version) != product.updated_at:
            _draft_error("name", "产品信息已变化，请刷新后重新选择。")
    for field, id_field, model, label in (
        ("category_name", "category_id", ProductCatalogCategory, "类别"),
        ("name", "name_id", ProductCatalogName, "品名"),
        ("unit_name", "unit_id", ProductionUnit, "单位"),
    ):
        record_id = draft[id_field]
        if sources[field] == "typed":
            if record_id:
                _draft_error(id_field, f"手填{label}不能携带维护记录编号。")
            continue
        record = model.objects.filter(pk=record_id, archived_at__isnull=True).first() if record_id else None
        if record is None or (field == "unit_name" and record.status != "ACTIVE"):
            _draft_error(id_field, f"请选择有效的{label}。")
        text = record.unit_name if field == "unit_name" else record.name
        if text != draft[field]:
            _draft_error(field, f"所选{label}与填写内容不一致。")
        if field == "name" and (str(record.category_id) != str(draft["category_id"]) or record.category.archived_at):
            _draft_error(field, "所选品名不属于当前类别。")
    if product:
        if str(draft["name_id"]) != str(product.name_id) or str(draft["category_id"]) != str(product.name.category_id):
            _draft_error("name", "产品关联与当前类别、品名不一致。")
        for field in ("item_number", "specification", "product_code"):
            if draft[field] != getattr(product, field):
                _draft_error(field, "货号、规格或编码改变后应解除旧产品关联。")
    else:
        for field in ("item_number", "specification", "product_code", "material"):
            if sources[field] == "selected" and draft[field]:
                _draft_error(field, "所选属性必须关联具体产品。")
    color_id = draft["color_id"]
    if sources["color_name"] == "selected":
        color = product.colors.filter(pk=color_id, archived_at__isnull=True).first() if product and color_id else None
        if color is None or color.value != draft["color_name"]:
            _draft_error("color_name", "所选颜色不属于当前产品或文字已变化。")
    elif color_id:
        _draft_error("color_id", "手填颜色不能携带维护记录编号。")
    if product and sources["material"] == "selected" and draft["material"] not in product.materials:
        _draft_error("material", "所选材质不属于当前产品。")
    unit = ProductionUnit.objects.filter(pk=draft["unit_id"]).first() if draft["unit_id"] else None
    # 输入来源和真实关联分开保存；JSON 中不放 UUID 对象或伪造的维护 ID。
    for field in ("category_id", "name_id", "unit_id", "color_id"):
        draft[field] = str(draft[field]) if draft[field] else None
    previous = existing_snapshot or {}
    return product, {
        "version": 2, "catalog_id": str(product.pk) if product else None,
        "catalog_version": product.updated_at.isoformat() if product else "",
        "name_id": draft["name_id"], "name": draft["name"],
        "category_id": draft["category_id"], "category_name": draft["category_name"],
        "product_code": draft["product_code"], "item_number": draft["item_number"],
        "specification": draft["specification"], "scale": product.scale if product else "",
        "unit_id": draft["unit_id"], "unit_name": draft["unit_name"], "unit_code": unit.unit_code if unit else "",
        "color_id": draft["color_id"], "color_name": draft["color_name"], "material": draft["material"],
        "thickness": previous.get("thickness", "") if str(previous.get("catalog_id")) == str(catalog_id) else "",
        "entry_state": "draft", "entry_draft": draft,
    }


def _selected_value(options, value, field, label):
    if value in (None, ""):
        if not options:
            return ""
        if len(options) == 1:
            return options[0]
        raise ValidationError({"product_selection": {field: f"请选择{label}。"}})
    if value not in options:
        raise ValidationError({"product_selection": {field: f"所选{label}不属于当前产品。"}})
    return value


@transaction.atomic
def resolve_product_selection(catalog_id, selection, *, existing_catalog_id=None, existing_snapshot=None):
    """调用方须在保存单据的同一事务内调用，以保持主档锁直到单据落库。"""
    if selection is not None:
        serializer = ProductSelectionSerializer(data=selection)
        serializer.is_valid(raise_exception=True)
        if "draft" in serializer.validated_data:
            return _resolve_draft(catalog_id, serializer.validated_data, existing_snapshot)
    if not catalog_id and not existing_catalog_id and selection is None and is_product_entry_snapshot(existing_snapshot):
        return None, deepcopy(existing_snapshot)
    if catalog_id in (None, ""):
        catalog_id = existing_catalog_id
    if not catalog_id:
        raise ValidationError({"product_catalog_id": "请选择产品。"})
    catalog_id = serializers.UUIDField().run_validation(catalog_id)
    unchanged = str(catalog_id) == str(existing_catalog_id) and selection is None
    # 先锁品名再锁产品，与产品维护、删除的锁序一致。
    name_id = ProductCatalog.objects.filter(pk=catalog_id).values_list("name_id", flat=True).first()
    if name_id is None:
        raise ValidationError({"product_catalog_id": "产品不存在或已删除。"})
    name = ProductCatalogName.objects.select_for_update(of=("self",)).select_related("category").filter(pk=name_id).first()
    if name is None:
        raise ValidationError({"product_catalog_id": "产品所属品名已删除。"})
    product = ProductCatalog.objects.select_for_update(of=("self",)).filter(pk=catalog_id, name_id=name_id).first()
    if product is None:
        raise ValidationError({"product_catalog_id": "产品不存在或已删除。"})
    product.name = name
    if unchanged:
        return product, deepcopy(existing_snapshot or {})
    if product.archived_at or name.archived_at or name.category.archived_at:
        raise ValidationError({"product_catalog_id": "产品或其品名、类别已停用，请重新选择。"})
    serializer = ProductSelectionSerializer(data=selection if selection is not None else {})
    serializer.is_valid(raise_exception=True)
    selected = serializer.validated_data
    try:
        version = parse_datetime(selected["catalog_version"])
    except ValueError as exc:
        raise ValidationError({"product_selection": {"catalog_version": "产品版本格式无效，请刷新后重新选择。"}}) from exc
    if version != product.updated_at:
        raise ValidationError({"product_selection": {"catalog_version": "产品信息已变化，请刷新后重新选择。"}})
    units = list(ProductionUnit.objects.filter(unit_name=product.unit, status="ACTIVE", archived_at__isnull=True)[:2])
    if len(units) != 1:
        raise ValidationError({"product_catalog_id": "该产品没有唯一有效的生产单位，请先在产品管理中设置单位。"})
    unit = units[0]
    colors = list(product.colors.filter(archived_at__isnull=True))
    color_id = _selected_value([str(color.pk) for color in colors], str(selected["color_id"]) if selected.get("color_id") else None, "color_id", "颜色")
    color = next((row for row in colors if str(row.pk) == color_id), None)
    material = _selected_value(product.materials, selected.get("material"), "material", "材质")
    thickness = _selected_value(product.thicknesses, selected.get("thickness"), "thickness", "壁厚")
    return product, {
        "version": 1, "catalog_id": str(product.pk), "catalog_version": product.updated_at.isoformat(),
        "name_id": str(name.pk), "name": name.name,
        "category_id": str(name.category_id), "category_name": name.category.name,
        "product_code": product.product_code, "item_number": product.item_number,
        "specification": product.specification, "scale": product.scale,
        "unit_id": str(unit.pk), "unit_name": unit.unit_name, "unit_code": unit.unit_code,
        "color_id": str(color.pk) if color else None, "color_name": color.value if color else "",
        "material": material, "thickness": thickness,
    }
