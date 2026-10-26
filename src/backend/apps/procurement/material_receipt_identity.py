"""以采购明细保存的身份解析收货材料，不再回读 BOM。"""
from uuid import UUID

from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.products.material_identity import resolve_bom_line_raw_material
from apps.products.models import RawMaterialInformation


class PurchaseMaterialIdentityError(Conflict):
    api_error_code = "PURCHASE_MATERIAL_IDENTITY_CONFLICT"


class PurchaseMaterialIdentityMissing(PurchaseMaterialIdentityError):
    api_error_code = "PURCHASE_MATERIAL_IDENTITY_MISSING"
    default_detail = "采购已保存明细缺少可唯一确认的材料身份，请核对采购明细。"


def build_purchase_material_snapshot(bom_line):
    material, _ = resolve_bom_line_raw_material(bom_line)
    if material is None or material.item_type != "MATERIAL":
        raise ValidationError({"lines": "采购明细必须关联有效的库存材料后才能保存。"})
    return {
        "schema_version": 1,
        "source": "PRODUCTION_PURCHASE",
        "raw_material_id": str(material.pk),
        "unit_id": str(material.unit_id),
    }


def get_purchase_material_id(purchase_line):
    snapshot = purchase_line.calculation_snapshot
    if not isinstance(snapshot, dict):
        raise PurchaseMaterialIdentityError("采购已保存的材料身份快照格式不正确，请核对采购明细。")
    if "raw_material_id" not in snapshot:
        return None
    try:
        return UUID(str(snapshot["raw_material_id"]))
    except (TypeError, ValueError) as exc:
        raise PurchaseMaterialIdentityError("采购已保存的材料 ID 格式不正确，请核对采购明细。") from exc


def resolve_purchase_material(purchase_line):
    material_id = get_purchase_material_id(purchase_line)
    materials = RawMaterialInformation.objects.select_related("unit")
    if material_id is not None:
        material = materials.filter(pk=material_id).first()
    else:
        material_number = purchase_line.raw_material_snapshot
        if not material_number:
            raise PurchaseMaterialIdentityMissing()
        # 历史导入允许重号；包括归档及其他类型，防止编号复用后静默换料。
        matches = list(materials.filter(material_number=material_number).order_by("pk")[:2])
        if len(matches) != 1:
            raise PurchaseMaterialIdentityMissing()
        material = matches[0]
    if material is None or material.archived_at is not None or material.item_type != "MATERIAL":
        raise PurchaseMaterialIdentityMissing()

    unit_id = purchase_line.calculation_snapshot.get("unit_id")
    if unit_id not in (None, ""):
        try:
            saved_unit_id = UUID(str(unit_id))
        except (TypeError, ValueError) as exc:
            raise PurchaseMaterialIdentityError("采购已保存的材料单位 ID 格式不正确，请核对采购明细。") from exc
        if saved_unit_id != material.unit_id:
            raise PurchaseMaterialIdentityError("库存材料单位与采购已保存的单位不一致，请核对采购明细。")
    return material
