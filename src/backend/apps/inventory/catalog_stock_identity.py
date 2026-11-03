"""目录身份保留已选属性；原管库存仍按实际批次原长和根数记账。"""
import hashlib
import json

from apps.material_catalog.saved_selection import validate_saved_material
from apps.material_catalog.snapshots import material_identity_key


CATALOG_STOCK_KINDS = ("CATALOG_RAW", "CATALOG_SEMI")


def build_catalog_stock_identity(*, material_catalog_id, material_selection_snapshot, raw_bar_length_m=None):
    selected = validate_saved_material(material_selection_snapshot, material_catalog_id=material_catalog_id)
    kind = "CATALOG_RAW" if selected["processing_state"] == "RAW" else "CATALOG_SEMI"
    properties = {}
    key = material_identity_key(selected)
    length = None
    if kind == "CATALOG_RAW" and selected["category_key"] == "TUBE":
        from .public_stock_identity import _positive_decimal
        from .stock_services import InventoryStockValidationError
        if selected["unit_name"] != "根":
            raise InventoryStockValidationError("原管库存沿用根制单位，请核对保存选料。", code="UNIT_MISMATCH")
        length = _positive_decimal(raw_bar_length_m, "raw_bar_length_m", places=2)
        properties = {"material_key": key, "raw_bar_length_m": format(length, ".2f")}
        key = hashlib.sha256(json.dumps(properties, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
    if kind == "CATALOG_SEMI":
        from .public_stock_identity import _make_identity, validate_public_identity
        details = selected.get("processing_details")
        if not isinstance(details, dict) or details.get("stock_kind") != "SEMI" or not details.get("unit_id"):
            from .stock_services import InventoryStockValidationError
            raise InventoryStockValidationError("加工结果须冻结实际长度或裁片及面料属性。", code="PUBLIC_STOCK_IDENTITY_INCOMPLETE")
        try:
            encoded = _make_identity(details)
        except (ValueError, TypeError) as error:
            from .stock_services import InventoryStockValidationError
            raise InventoryStockValidationError("加工属性不是可保存的快照。", code="PUBLIC_STOCK_IDENTITY_INVALID") from error
        legacy = validate_public_identity(encoded)["identity_snapshot"]
        if (legacy["stock_kind"] != "SEMI" or legacy["completed_craft"] != selected["completed_craft"]
                or legacy["semi_kind"] != selected["semi_kind"] or legacy["unit_id"] != selected["unit_id"]):
            from .stock_services import InventoryStockValidationError
            raise InventoryStockValidationError("加工属性、单位或工艺与材料快照不一致。", code="PUBLIC_STOCK_IDENTITY_INVALID")
        properties = {name: value for name, value in legacy.items() if name not in {"schema_version", "stock_kind", "unit_id", "unit_name"}}
        physical = {name: value for name, value in properties.items() if name not in {"category", "part_name"}}
        fabric = selected.get("fabric_material_selection_snapshot")
        fabric_key = material_identity_key(validate_saved_material(fabric)) if fabric is not None else None
        key = hashlib.sha256(json.dumps({"material_key": key, "processing": physical, "fabric_key": fabric_key}, ensure_ascii=False,
                                       sort_keys=True, separators=(",", ":")).encode("utf8")).hexdigest()
    snapshot = {"schema_version": 2, "stock_kind": kind, "unit_id": selected["unit_id"],
                "unit_name": selected["unit_name"], **properties, "material_selection_snapshot": selected}
    return {"stock_kind": kind, "identity_key": key, "identity_snapshot": snapshot,
            "raw_material_id": None, "raw_bar_length_m": length, "unit_id": selected["unit_id"]}


def validate_catalog_stock_identity(identity):
    from .stock_services import InventoryStockValidationError

    snapshot = identity.get("identity_snapshot") if isinstance(identity, dict) else None
    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 2:
        raise InventoryStockValidationError("新材料库存快照结构或版本无效。", code="PUBLIC_STOCK_IDENTITY_INVALID")
    selected = validate_saved_material(snapshot.get("material_selection_snapshot"))
    expected = build_catalog_stock_identity(material_catalog_id=selected["catalog_id"], material_selection_snapshot=selected,
        raw_bar_length_m=snapshot.get("raw_bar_length_m"))
    normalized = dict(identity)
    if expected["raw_bar_length_m"] is not None:
        from .public_stock_identity import _positive_decimal
        normalized["raw_bar_length_m"] = _positive_decimal(identity.get("raw_bar_length_m"), "raw_bar_length_m", places=2)
    if normalized != expected:
        raise InventoryStockValidationError("新材料库存索引与保存内容不一致。", code="PUBLIC_STOCK_IDENTITY_INVALID")
    return expected


def catalog_processed_identity(*, bom_line, unit, processing_details):
    """既有加工入口先验证真实工艺和输出数量；这里只冻结其实际实物字段。"""
    selected = validate_saved_material(bom_line.material_selection_snapshot, material_catalog_id=bom_line.material_catalog_id)
    selected.update(processing_state="PROCESSED", processing_stage=processing_details["completed_craft"]["code"],
                    completed_craft=processing_details["completed_craft"], semi_kind=processing_details["semi_kind"],
                    unit_id=str(unit.pk), unit_name=unit.unit_name, processing_details=processing_details)
    attrs = selected["attributes"]
    if processing_details["semi_kind"] == "PIPE":
        # 库存实物为切割后的管段，基础长管长度不能继续参与加工结果身份。
        attrs["length"] = f'{processing_details["cutting_length_mm"]} mm'
    elif processing_details["semi_kind"] == "CUTTING":
        fabric = getattr(bom_line, "fabric_source_line", None)
        if getattr(fabric, "material_catalog_id", None):
            selected["fabric_material_selection_snapshot"] = validate_saved_material(
                fabric.material_selection_snapshot, material_catalog_id=fabric.material_catalog_id)
    if processing_details.get("color"):
        attrs["color"] = processing_details["color"]
    else:
        attrs.pop("color", None)
    selected["display_name"] = " / ".join([selected["name"], *attrs.values(), unit.unit_name])
    return build_catalog_stock_identity(material_catalog_id=bom_line.material_catalog_id, material_selection_snapshot=selected)
