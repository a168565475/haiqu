"""BOM 部位、裁片引用既有品名；引用不是原料投入或已完成工艺。"""
from copy import deepcopy

from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.material_catalog.definitions import TEMPLATES
from apps.material_catalog.models import MaterialCatalog
from apps.reference_data.models import ProductionUnit


REFERENCE_KIND = "BOM_COMPONENT_REFERENCE"
SOURCE_ATTRIBUTE_FIELDS = {"material", "color", "fabric_spec", "width"}


def is_component_catalog_reference(snapshot):
    return isinstance(snapshot, dict) and snapshot.get("selection_kind") == REFERENCE_KIND


def validate_component_catalog_reference(line):
    snapshot = line.material_selection_snapshot
    if (not line.material_catalog_id or snapshot.get("catalog_id") != str(line.material_catalog_id)
            or snapshot.get("schema_version") != 1
            or snapshot.get("category_key") != "FABRIC_SEMI"
            or snapshot.get("template_key") != "FABRIC_SEMI"
            or snapshot.get("scope") != "BASE"
            or snapshot.get("completed_craft") is not None or snapshot.get("semi_kind") is not None
            or snapshot.get("name") != line.part_name or snapshot.get("unit_name") != line.unit
            or not snapshot.get("catalog_version") or not snapshot.get("unit_id")
            or not isinstance(snapshot.get("attributes"), dict)):
        raise ValidationError({"material_selection": "部位或裁片的品名引用快照不完整，不能当作原料或完成工艺。"})
    identity_version = snapshot.get("identity_attributes_version")
    if identity_version is not None and (
            type(identity_version) is not int or identity_version != 1 or not snapshot["attributes"]):
        raise ValidationError({"material_selection": "部位或裁片的属性身份版本无效。"})


def _same_selection(selection, snapshot, unit):
    return (selection.get("attributes") == snapshot.get("attributes")
            and selection.get("scope") == snapshot.get("scope")
            and selection.get("processing_state") == snapshot.get("processing_state")
            and selection.get("completed_craft") == snapshot.get("completed_craft")
            and selection.get("semi_kind") == snapshot.get("semi_kind")
            and (str(selection.get("unit_id") or "") == str(snapshot.get("unit_id") or "")
                 if selection.get("unit_id") else selection.get("unit_name") == snapshot.get("unit_name"))
            and unit == snapshot.get("unit_name"))


def apply_component_catalog_selection(line, data, *, old, request, persist, versions, selection_permission):
    """返回 False 时保留旧 typed 裁片的通用材料快照处理，不转换历史。"""
    previous = old.material_selection_snapshot if old and old.material_catalog_id else None
    catalog_id = data.get("material_catalog_id", old.material_catalog_id if old else None)
    selection = data.get("material_selection")
    same_catalog = bool(previous and str(catalog_id) == str(old.material_catalog_id))
    unchanged = same_catalog and (not selection or (
        _same_selection(selection, previous, line.unit)
        and (not is_component_catalog_reference(previous)
             or selection.get("catalog_version") == previous.get("catalog_version"))))
    if unchanged and not is_component_catalog_reference(previous):
        return False
    if unchanged:
        if line.unit != previous.get("unit_name"):
            raise ValidationError({"unit": "更改部位单位时，请同步选择品名引用的单位。"})
        snapshot = deepcopy(previous)
    else:
        if not selection:
            raise ValidationError({"material_selection": "更换部位或裁片品名时，请重新选择既有档案。"})
        if not request.user.has_perm(selection_permission):
            raise PermissionDenied("当前账号没有选择此品名档案的权限。")
        query = MaterialCatalog.objects.filter(pk=catalog_id, archived_at__isnull=True,
                                                category_key="FABRIC_SEMI", template_key="FABRIC_SEMI")
        catalog = (query.select_for_update() if persist else query).first()
        if catalog is None:
            raise ValidationError({"material_catalog_id": "请选择既有且未归档的裁片品名档案。"})
        version = selection.get("catalog_version")
        if not version:
            raise PreconditionRequired("请选择带内容版本的品名档案。")
        if version != versions.setdefault(catalog.pk, catalog.updated_at.isoformat()):
            raise PreconditionFailed("品名档案已变化，请刷新后重选；BOM草稿仍保留。")
        if (selection.get("scope") != "BASE" or selection.get("processing_state") != "PROCESSED"
                or selection.get("completed_craft") is not None or selection.get("semi_kind") is not None):
            raise ValidationError({"material_selection": "部位和裁片只引用基础品名，不选择或伪造已完成工艺。"})
        attrs = selection.get("attributes")
        fields = {field["key"] for field in TEMPLATES[catalog.template_key]["fields"] if field["kind"] != "unit"}
        if (not isinstance(attrs, dict) or set(attrs) - fields
                or any(not isinstance(value, str) or not value.strip() or value.strip() in {"/", "-", "—"}
                       for value in attrs.values())):
            raise ValidationError({"attributes": "品名属性须为已维护的实际值，也可以不选择属性。"})
        attrs = {key: value.strip() for key, value in attrs.items()}
        same_attributes = (same_catalog and is_component_catalog_reference(previous)
                           and attrs == previous.get("attributes"))
        if set(attrs) & SOURCE_ATTRIBUTE_FIELDS and not same_attributes:
            raise ValidationError({"attributes": "材质、颜色、面料规格和门幅来自关联原料，不能在部位或裁片品名中另选。"})
        if not same_attributes:
            options = set(catalog.attribute_values.filter(scope="BASE", archived_at__isnull=True)
                          .values_list("field_key", "value"))
            for key, value in attrs.items():
                if (key, value) not in options:
                    raise ValidationError({"attributes": f"“{value}”不是当前品名已维护的属性。"})
        # 实物流转单位属于当前 BOM，不借选品名扩写目录的 allowed_units。
        unit = ProductionUnit.objects.filter(unit_name=line.unit, status="ACTIVE", archived_at__isnull=True).first()
        if (unit is None or (selection.get("unit_id") and str(selection["unit_id"]) != str(unit.pk))
                or (selection.get("unit_name") and selection["unit_name"] != line.unit)):
            raise ValidationError({"unit": "请选择当前 BOM 的有效单位，品名引用单位须与本行一致。"})
        snapshot = {
            "schema_version": 1, "selection_kind": REFERENCE_KIND,
            "catalog_id": str(catalog.pk), "catalog_version": catalog.updated_at.isoformat(),
            "category_key": catalog.category_key, "template_key": catalog.template_key, "name": catalog.name,
            "scope": "BASE", "processing_state": "PROCESSED", "processing_stage": "",
            "completed_craft": None, "semi_kind": None, "attributes": deepcopy(attrs),
            "unit_id": str(unit.pk), "unit_name": unit.unit_name,
            "display_name": " / ".join([catalog.name, *attrs.values(), unit.unit_name]),
        }
        if same_attributes:
            if previous.get("identity_attributes_version") is not None:
                snapshot["identity_attributes_version"] = previous["identity_attributes_version"]
        elif attrs:
            # 不因刷新目录名称/版本而重新解释既有库存；只有新属性启用新身份。
            snapshot["identity_attributes_version"] = 1
        if line.component_kind == "SEWN_PART":
            if not same_attributes and not line.specification.strip():
                line.specification = next((attrs[key] for key in ("size", "specification", "model") if attrs.get(key)), "")
    line.material_catalog_id = catalog_id
    line.material_selection_snapshot = snapshot
    line.part_name = snapshot["name"]
    line.material_quantity = None
    validate_component_catalog_reference(line)
    return True
