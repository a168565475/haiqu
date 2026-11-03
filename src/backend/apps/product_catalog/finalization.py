"""仅由 BOM 最终确认调用，将已核对的临时产品信息正式建档。"""
from copy import deepcopy
from uuid import uuid4

from django.db import transaction
from django.utils.dateparse import parse_datetime
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.access_control import module_policy
from apps.core.audit import write_audit_log
from apps.reference_data.models import ProductionUnit

from .models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName
from .selection import is_product_entry_snapshot, resolve_product_selection


def _require(request, permission, message):
    if request is None or not module_policy.has_permission(request, permission):
        raise PermissionDenied(message)


def _error(field, message):
    raise ValidationError({"product_selection": {"draft": {field: message}}})


def _audit(instance, object_type, request, actor_employee, *, action="CREATED", before=None, after=None):
    write_audit_log(object_type=object_type, object_id=instance.pk, action=action,
                    actor_employee=actor_employee, before_data=before, after_data=after, request=request)


@transaction.atomic
def finalize_product_entry(*, snapshot, catalog_id=None, request, actor_employee=None):
    """精确复用或建立最终产品；任何失败都随外层 BOM 确认事务回滚。"""
    if not is_product_entry_snapshot(snapshot):
        return resolve_product_selection(catalog_id, None, existing_catalog_id=catalog_id, existing_snapshot=snapshot)
    selection = {"draft": snapshot["entry_draft"]}
    if snapshot.get("catalog_version"):
        selection["catalog_version"] = snapshot["catalog_version"]
    _, current = resolve_product_selection(catalog_id, selection,
        existing_catalog_id=catalog_id, existing_snapshot=snapshot)
    for field, label in (("category_name", "类别"), ("name", "品名"), ("unit_name", "单位")):
        if not current.get(field, "").strip():
            _error(field, f"确认产品前必须填写{label}。")

    units = ProductionUnit.objects.select_for_update()
    unit = units.filter(pk=current["unit_id"]).first() if current.get("unit_id") else units.filter(unit_name=current["unit_name"]).first()
    if current.get("unit_id") and (unit is None or unit.unit_name != current["unit_name"]):
        _error("unit_name", "所选单位已变化，请重新核对。")
    if unit is None:
        _require(request, "reference_data.add_productionunit", "确认新的单位需要生产维护的单位新增权限。")
        # 编号是正式单位创建后的内部标识，不在前序单据中伪造关联。
        unit, created = ProductionUnit.objects.get_or_create(unit_name=current["unit_name"],
            defaults={"unit_code": "BOM" + uuid4().hex[:17]})
        if created:
            _audit(unit, "PRODUCTION_UNIT", request, actor_employee,
                   after={"unit_name": unit.unit_name, "source": "BOM_CONFIRMATION"})
        unit = units.get(pk=unit.pk)
    if unit.archived_at or unit.status != "ACTIVE":
        _error("unit_name", "同名单位已停用，请在生产维护中核对。")

    categories = ProductCatalogCategory.objects.select_for_update()
    category = categories.filter(pk=current["category_id"]).first() if current.get("category_id") else categories.filter(name=current["category_name"]).first()
    if current.get("category_id") and (category is None or category.name != current["category_name"]):
        _error("category_name", "所选类别已变化，请重新核对。")
    if category is None:
        _require(request, "product_catalog.add_productcatalog", "确认新的产品类别需要产品管理新增权限。")
        category, created = ProductCatalogCategory.objects.get_or_create(name=current["category_name"])
        if created:
            _audit(category, "PRODUCT_CATALOG_CATEGORY", request, actor_employee, after={"name": category.name})
        category = categories.get(pk=category.pk)
    if category.archived_at:
        _error("category_name", "同名产品类别已停用，请重新核对。")
    if current.get("category_id") and str(category.pk) != str(current["category_id"]):
        _error("category_name", "产品类别已变化，请重新核对。")

    name = ProductCatalogName.objects.filter(category=category, name=current["name"]).first()
    if name is None:
        _require(request, "product_catalog.add_productcatalog", "确认新的品名需要产品管理新增权限。")
        name, created = ProductCatalogName.objects.get_or_create(category=category, name=current["name"])
        if created:
            _audit(name, "PRODUCT_CATALOG_NAME", request, actor_employee,
                   after={"category_id": str(category.pk), "name": name.name})
    # 与产品管理统一先锁品名再锁产品，串行处理同品名下的重复确认。
    name = ProductCatalogName.objects.select_for_update().get(pk=name.pk)
    if (name.archived_at or name.name != current["name"] or name.category_id != category.pk
            or (current.get("name_id") and str(name.pk) != str(current["name_id"]))):
        _error("name", "品名已停用或发生变化，请重新核对。")
    products = ProductCatalog.objects.select_for_update().filter(name=name)
    if catalog_id:
        product = products.filter(pk=catalog_id, archived_at__isnull=True).first()
        if product is None:
            _error("name", "所选产品已停用或不属于当前品名。")
        if parse_datetime(current["catalog_version"]) != product.updated_at:
            _error("name", "产品信息已变化，请刷新后重新核对。")
    else:
        matches = list(products.filter(item_number=current["item_number"], specification=current["specification"])[:2])
        if len(matches) > 1:
            _error("item_number", "此货号和规格存在多条产品，请明确选择已有产品后确认。")
        product = matches[0] if matches else None
        if product and product.archived_at:
            _error("item_number", "相同货号和规格的产品已停用，请先核对产品管理。")
    created_product = product is None
    if created_product:
        for field, label in (("item_number", "货号"), ("product_code", "产品编码")):
            if not current[field].strip():
                _error(field, f"新产品正式建档前必须填写{label}。")
        _require(request, "product_catalog.add_productcatalog", "确认新产品需要产品管理新增权限。")
        product = ProductCatalog.objects.create(name=name, item_number=current["item_number"],
            product_code=current["product_code"], specification=current["specification"], unit=unit.unit_name,
            scale=current.get("scale", ""), materials=[])
    elif any(getattr(product, field) != current[field] for field in ("item_number", "product_code", "specification")):
        _error("product_code", "所填货号、规格、产品编码与已有产品不一致，请重新选择或核对，不能覆盖其他产品。")
    elif product.unit != unit.unit_name:
        _error("unit_name", "该产品的单位与本次填写不同，请在产品管理中核对后确认。")

    before = {"colors": list(product.colors.filter(archived_at__isnull=True).values_list("value", flat=True)),
              "materials": list(product.materials)}
    color = product.colors.filter(value=current["color_name"]).first() if current["color_name"] else None
    add_color = bool(current["color_name"] and (color is None or color.archived_at))
    add_material = bool(current["material"] and current["material"] not in product.materials)
    if not created_product and (add_color or add_material):
        _require(request, "product_catalog.change_productcatalog", "补充产品颜色或材质需要产品管理编辑权限。")
    if add_color:
        if color is None:
            color = ProductCatalogColor.objects.create(product=product, value=current["color_name"])
        else:
            color.archived_at = None
            color.archived_by_employee = None
            color.archive_reason = ""
            color.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
    if add_material:
        product.materials = [*product.materials, current["material"]]
    if created_product or add_color or add_material:
        product.save(update_fields=["materials", "updated_at"])
        name.save(update_fields=["updated_at"])
        _audit(product, "PRODUCT_CATALOG", request, actor_employee,
            action="CREATED" if created_product else "UPDATED", before=None if created_product else before,
            after={"name_id": str(name.pk), "item_number": product.item_number, "specification": product.specification,
                   "product_code": product.product_code, "color": current["color_name"], "material": current["material"],
                   "source": "BOM_CONFIRMATION"})
    final = deepcopy(current)
    final.update(catalog_id=str(product.pk), catalog_version=product.updated_at.isoformat(),
        category_id=str(category.pk), name_id=str(name.pk), unit_id=str(unit.pk),
        unit_name=unit.unit_name, unit_code=unit.unit_code, color_id=str(color.pk) if color else None,
        entry_state="confirmed")
    return product, final
