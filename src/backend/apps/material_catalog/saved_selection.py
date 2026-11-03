"""验证已保存的材料事实；不查询当前目录、选项或 BOM，不补齐历史缺项。"""
from copy import deepcopy
from uuid import UUID

from rest_framework.exceptions import ValidationError

from .definitions import CATEGORIES, SPRAY_FIELDS, TEMPLATES


def validate_saved_material(snapshot, *, material_catalog_id=None):
    def invalid(message):
        raise ValidationError({"material_selection_snapshot": message})

    if not isinstance(snapshot, dict) or type(snapshot.get("schema_version")) is not int or snapshot["schema_version"] != 1:
        invalid("材料快照版本缺失或不受支持，请核对来源单据。")
    required = {"catalog_id", "catalog_version", "category_key", "template_key", "name", "scope",
                "processing_state", "processing_stage", "completed_craft", "semi_kind", "attributes",
                "unit_id", "unit_name", "display_name"}
    if not required.issubset(snapshot):
        invalid("来源材料快照不完整，不能从当前目录补写历史内容。")
    for field in ("catalog_id", "unit_id"):
        try:
            parsed = str(UUID(str(snapshot[field])))
        except (ValueError, TypeError, AttributeError):
            invalid(f"{field}不是有效编号。")
        if parsed != snapshot[field]:
            invalid(f"{field}不是已规范化的编号。")
    if material_catalog_id is not None and str(material_catalog_id) != snapshot["catalog_id"]:
        invalid("材料关联与保存快照不一致。")
    for field in ("catalog_version", "category_key", "template_key", "name", "unit_name", "display_name"):
        if not isinstance(snapshot[field], str) or not snapshot[field].strip():
            invalid(f"{field}须为非空文字。")
    template = TEMPLATES.get(snapshot["template_key"])
    categories = {item["key"]: {row["key"] for row in item["templates"]} for item in CATEGORIES}
    if template is None or snapshot["template_key"] not in categories.get(snapshot["category_key"], set()):
        invalid("材料类别与模板不一致。")
    if not isinstance(snapshot["scope"], str) or not isinstance(snapshot["processing_state"], str) or snapshot["scope"] not in {"BASE", "SPRAY"} or snapshot["processing_state"] not in {"RAW", "PROCESSED"}:
        invalid("材料属性组或加工状态无效。")
    fields = {row["key"] for row in template["fields"] if row["kind"] != "unit"}
    if snapshot["scope"] == "SPRAY":
        fields.update(row["key"] for row in SPRAY_FIELDS if row["kind"] != "unit")
    attrs = snapshot["attributes"]
    if not isinstance(attrs, dict) or not attrs or any(key not in fields for key in attrs):
        invalid("材料属性为空或包含不支持的字段。")
    if any(not isinstance(value, str) or not value.strip() or len(value) > 300 for value in attrs.values()):
        invalid("材料属性须为明确的文字。")
    if snapshot.get("product_color_id"):
        try:
            if str(UUID(str(snapshot["product_color_id"]))) != snapshot["product_color_id"]:
                invalid("普通颜色编号不是已规范化的编号。")
        except (ValueError, TypeError, AttributeError):
            invalid("普通颜色编号无效。")
        for field, limit in (("color_card", 100), ("color_code", 100), ("color_name", 200)):
            if not isinstance(snapshot.get(field), str) or len(snapshot[field]) > limit:
                invalid("普通颜色快照必须保留完整的色卡、色号与颜色名。")
        # 加工快照会将 attributes.color 换成喷塑/加工颜色，顶层仍保留原普通颜色事实。
        if (snapshot["processing_state"] == "RAW" and snapshot["color_name"] != attrs.get("color")) or snapshot["scope"] != "BASE" or snapshot["category_key"] == "AUXILIARY":
            invalid("普通颜色快照与材料基础颜色不一致。")
    # 正式 BOM 的原管选料不含目录长度；实际原长由采购/库存独立校验。
    # 加工管材仍须保留加工后的长度，不查询当前目录或补写旧快照。
    from apps.boms.catalog_selection import required_fields
    for field in required_fields(snapshot["template_key"], attrs, require_tube_length=snapshot["processing_state"] != "RAW"):
        if attrs.get(field, "").strip() in {"", "/", "-", "—"}:
            invalid(f"保存材料缺少必要属性：{field}。")
    if snapshot["processing_state"] == "RAW":
        if snapshot["processing_stage"] != "RAW" or snapshot["completed_craft"] is not None or snapshot["semi_kind"] is not None:
            invalid("原料快照不能带已完成工艺。")
        if snapshot["category_key"] == "FABRIC_SEMI":
            invalid("裁片必须保留加工结果状态。")
    else:
        craft = snapshot["completed_craft"]
        if not isinstance(craft, dict) or set(craft) != {"id", "craft_type", "code"}:
            invalid("半成品须保留完整已完成工艺。")
        try:
            if str(UUID(str(craft["id"]))) != craft["id"]:
                invalid("工艺编号不是已规范化的编号。")
        except (ValueError, TypeError, AttributeError):
            invalid("工艺编号无效。")
        codes = {"INTERNAL": {"METAL", "CUTTING", "SEWING", "ASSEMBLY"},
                 "EXTERNAL": {"POWDER_COATING", "SCREEN_PRINTING", "EMBROIDERY", "CUTTING", "SEWING"}}
        if not isinstance(craft["craft_type"], str) or not isinstance(craft["code"], str) or craft["craft_type"] not in codes or craft["code"] not in codes[craft["craft_type"]]:
            invalid("已完成工艺类型或代码无效。")
        if snapshot["processing_stage"] != craft["code"] or not isinstance(snapshot["semi_kind"], str) or snapshot["semi_kind"] not in {"PIPE", "CUTTING", "HARDWARE"}:
            invalid("加工阶段与半成品种类不完整。")
    return deepcopy(snapshot)
