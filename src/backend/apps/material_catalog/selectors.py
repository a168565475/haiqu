import re

from django.db.models import Q

from apps.inventory.models import Warehouse
from apps.reference_data.pinyin_search import build_pinyin_search

from .definitions import CATEGORIES, SPRAY_FIELDS
from .models import MaterialCatalog


def _pinyin_search_term(query):
    compact = re.sub(r"[\s_-]+", "", query.casefold())
    return compact if re.fullmatch(r"[a-z0-9]+", compact) and re.search(r"[a-z]", compact) else ""


def _matches_pinyin(name, term):
    return bool(term) and any(term in candidate for candidate in build_pinyin_search(name).split())


def catalog_list(*, category="", query=""):
    queryset = MaterialCatalog.objects.filter(archived_at__isnull=True)
    if category:
        queryset = queryset.filter(category_key=category)
    if query:
        term = _pinyin_search_term(query)
        if term:
            # 在分类和归档过滤后、分页前匹配全部名称；只取标识和名称，不加载属性。
            matched_ids = [pk for pk, name in queryset.order_by().values_list("pk", "name") if _matches_pinyin(name, term)]
            queryset = queryset.filter(Q(name__icontains=query) | Q(pk__in=matched_ids))
        else:
            queryset = queryset.filter(name__icontains=query)
    return queryset.order_by("name", "id")


def catalog_summary(catalog):
    return {
        "id": str(catalog.pk), "category_key": catalog.category_key,
        "template_key": catalog.template_key, "name": catalog.name,
        "spray_enabled": catalog.spray_enabled, "updated_at": catalog.updated_at.isoformat(),
    }


def catalog_detail(catalog):
    from .colors import color_metadata, uses_product_color_identity

    fabric_colors = uses_product_color_identity(catalog)
    return {
        **catalog_summary(catalog),
        "base_warehouse_id": str(catalog.base_warehouse_id) if catalog.base_warehouse_id else None,
        "semi_warehouse_id": str(catalog.semi_warehouse_id) if catalog.semi_warehouse_id else None,
        "values": [
            {"id": str(row.pk), "scope": row.scope, "field_key": row.field_key,
             "value": row.product_color.color_name if fabric_colors and row.product_color_id else row.value,
             "parent_id": str(row.parent_id) if row.parent_id else None,
             **(color_metadata(row.product_color) if fabric_colors and row.product_color_id else
                {"product_color_id": None, "color_card": "", "color_code": "", "color_name": row.value}
                if row.scope == "BASE" and row.field_key == "color" and fabric_colors else {})}
            for row in catalog.attribute_values.filter(archived_at__isnull=True).select_related("product_color")
        ],
        "units": [
            {"id": str(row.pk), "scope": row.scope, "unit_id": str(row.unit_id), "unit_name": row.unit.unit_name}
            for row in catalog.allowed_units.filter(archived_at__isnull=True).select_related("unit")
        ],
    }


def catalog_options():
    return {
        "categories": CATEGORIES, "spray_fields": SPRAY_FIELDS,
        # 不暴露公共单位候选；各品名单位从自己的详情读取。
        "units": [],
        "warehouses": [
            {"id": str(row.pk), "warehouse_number": row.warehouse_number,
             "warehouse_name": row.warehouse_name, "warehouse_type": row.warehouse_type}
            for row in Warehouse.objects.filter(status="ACTIVE").order_by("warehouse_number", "id")
        ],
    }
