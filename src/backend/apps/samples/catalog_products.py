"""样品产品从新产品选择或上游已保存快照取得身份与固定属性。"""
from copy import deepcopy

from rest_framework.exceptions import ValidationError

from apps.product_catalog.selection import is_product_entry_snapshot, resolve_product_selection


def catalog_sample_values(catalog, snapshot, *, product_image=None):
    return {
        "product": None, "product_catalog": catalog, "product_selection_snapshot": deepcopy(snapshot),
        "product_number_snapshot": "", "product_code_snapshot": snapshot.get("product_code", ""),
        "item_number_snapshot": snapshot.get("item_number", ""), "product_name": snapshot.get("name", ""),
        "specification": snapshot.get("specification", ""), "material_snapshot": snapshot.get("material", ""),
        "category": None, "category_name_snapshot": snapshot.get("category_name", ""), "product_image": product_image,
    }


def apply_catalog_selection(values, *, existing=None, source=None):
    """仅消费选择字段；旧产品/自定义产品的既有处理由调用方保留。"""
    submitted = "product_catalog_id" in values
    catalog_id = values.pop("product_catalog_id", None)
    selection = values.pop("product_selection", None)
    if source is not None and (source.product_catalog_id or is_product_entry_snapshot(source.product_selection_snapshot)):
        if values.get("product") or (submitted and str(catalog_id or "") != str(source.product_catalog_id or "")) or selection is not None:
            raise ValidationError({"product_catalog_id": "来源产品必须沿用上游已保存的选择。"})
        values.update(catalog_sample_values(source.product_catalog, source.product_selection_snapshot, product_image=getattr(source, "product_image", None)))
        return True
    if not submitted and existing is not None:
        catalog_id = existing.product_catalog_id
    if catalog_id or selection is not None or is_product_entry_snapshot(getattr(existing, "product_selection_snapshot", None)):
        if values.get("product"):
            raise ValidationError({"product_catalog_id": "新旧产品不能同时选择。"})
        catalog, snapshot = resolve_product_selection(
            catalog_id, selection,
            existing_catalog_id=existing.product_catalog_id if existing else None,
            existing_snapshot=existing.product_selection_snapshot if existing else None,
        )
        image = existing.product_image if existing is not None and existing.product_catalog_id == getattr(catalog, "pk", None) else None
        values.update(catalog_sample_values(catalog, snapshot, product_image=image))
        return True
    if existing is not None and existing.product_catalog_id:
        values.update(product_catalog=None, product_selection_snapshot={}, product_number_snapshot="",
                      product_code_snapshot="", item_number_snapshot="", material_snapshot="", product_image=None)
    return False


def sample_detail_color_values(product, color, color_code=""):
    if color is not None:
        return {"product_color": color, "color_card_snapshot": color.color_card,
                "color_code_snapshot": color_code or color.color_code, "color_name_snapshot": color.color_name,
                "unit_code": product.product_selection_snapshot.get("unit_code", "PCS")}
    if product.product_catalog_id or is_product_entry_snapshot(product.product_selection_snapshot):
        snapshot = product.product_selection_snapshot
        return {"product_color": None, "color_card_snapshot": "", "color_code_snapshot": "",
                "color_name_snapshot": snapshot.get("color_name", ""), "unit_code": snapshot["unit_code"]}
    if color is None:
        raise ValidationError({"products": "自定义或旧产品的颜色明细必须选择颜色。"})
    return {"product_color": color, "color_card_snapshot": color.color_card,
            "color_code_snapshot": color_code or color.color_code, "color_name_snapshot": color.color_name,
            "unit_code": "PCS"}
