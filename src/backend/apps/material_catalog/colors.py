"""普通颜色保持 ProductColor 单条身份；旧的纯文字颜色不推断色卡。"""
from rest_framework.exceptions import ValidationError


COLOR_FIELDS = ("product_color_id", "color_card", "color_code", "color_name")


def uses_product_color_identity(catalog, scope="BASE", key="color"):
    return catalog.category_key == "FABRIC" and scope == "BASE" and key == "color"


def color_metadata(color):
    return {"product_color_id": str(color.pk), "color_card": color.color_card,
            "color_code": color.color_code, "color_name": color.color_name}


def color_identity(value, data=None):
    data = data or {}
    identity = {"color_card": data.get("color_card", ""), "color_code": data.get("color_code", ""),
                "color_name": data.get("color_name", value)}
    for key, limit in (("color_card", 100), ("color_code", 100), ("color_name", 200)):
        text = identity[key]
        if not isinstance(text, str) or len(text.strip()) > limit:
            raise ValidationError({key: f"必须为不超过{limit}字的文字。"})
        identity[key] = text.strip()
    if not identity["color_name"] or identity["color_name"] != value.strip():
        raise ValidationError({"color_name": "颜色名称必须与所选颜色值一致，且不能为空。"})
    return identity


def unchanged_color(option, data):
    """未编辑的旧目录记录可保留停用颜色；明确换色仍须验证活动公共项。"""
    if option is None or option.archived_at is not None:
        return False
    if not any(key in data for key in COLOR_FIELDS):
        return option.value == data["value"]
    identity = color_identity(data["value"], data)
    if option.product_color_id:
        color = option.product_color
        return (str(data.get("product_color_id") or color.pk) == str(color.pk)
                and identity == {key: getattr(color, key) for key in identity})
    return (not data.get("product_color_id") and not identity["color_card"] and not identity["color_code"]
            and option.value == identity["color_name"])


def unchanged_snapshot_color(selection, snapshot):
    if not any(key in selection for key in COLOR_FIELDS):
        return True  # 老调用未编辑颜色身份时保留原快照。
    return (str(selection.get("product_color_id") or "") == str(snapshot.get("product_color_id") or "")
            and selection.get("color_card", "") == snapshot.get("color_card", "")
            and selection.get("color_code", "") == snapshot.get("color_code", "")
            and selection.get("color_name", selection["attributes"].get("color", ""))
            == snapshot.get("color_name", snapshot["attributes"].get("color", "")))
