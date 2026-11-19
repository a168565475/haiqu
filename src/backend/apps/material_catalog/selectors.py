import re

from django.db.models import Q
from rest_framework.exceptions import ValidationError

from apps.inventory.models import Warehouse
from apps.reference_data.models import ProductionUnit
from apps.reference_data.pinyin_search import build_pinyin_search

from .definitions import CATEGORIES, SPRAY_FIELDS
from .colors import catalog_color_metadata, color_identity, uses_product_color_identity
from .public_configuration import _validate_color_source
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
    fabric_colors = uses_product_color_identity(catalog)
    return {
        **catalog_summary(catalog),
        "base_warehouse_id": str(catalog.base_warehouse_id) if catalog.base_warehouse_id else None,
        "semi_warehouse_id": str(catalog.semi_warehouse_id) if catalog.semi_warehouse_id else None,
        "values": [
            {"id": str(row.pk), "scope": row.scope, "field_key": row.field_key,
             "value": row.product_color.color_name if fabric_colors and row.product_color_id else row.value,
             "parent_id": str(row.parent_id) if row.parent_id else None,
             **({"selectable": False} if fabric_colors and row.product_color_id and
                (row.product_color.status != "ACTIVE" or row.product_color.archived_at) else {}),
             **(catalog_color_metadata(row) if row.scope == "BASE" and row.field_key == "color" and fabric_colors else {})}
            for row in catalog.attribute_values.filter(archived_at__isnull=True).select_related("product_color")
        ],
        "units": [
            {"id": str(row.pk), "scope": row.scope, "unit_id": str(row.unit_id), "unit_name": row.unit.unit_name,
             **({"selectable": False} if row.unit.status != "ACTIVE" or row.unit.archived_at else {})}
            for row in catalog.allowed_units.filter(archived_at__isnull=True).select_related("unit")
        ],
    }


def find_catalog_attribute(catalog, scope, key, value, *, parent_value=None, color=None):
    ordinary_color = uses_product_color_identity(catalog, scope, key)
    if key == "color":
        _validate_color_source(ordinary_color, color)
    options = catalog.attribute_values.filter(scope=scope, field_key=key, archived_at__isnull=True)
    if key == "section_size":
        options = options.filter(parent__catalog=catalog, parent__field_key="shape", parent__scope="BASE",
                                 parent__value=parent_value, parent__archived_at__isnull=True)
    if ordinary_color:
        color = color or {}
        identity = color_identity(value, color)
        if color.get("product_color_id"):
            option = options.select_related("product_color").filter(product_color_id=color["product_color_id"],
                product_color__status="ACTIVE", product_color__archived_at__isnull=True).first()
            if option and (option.product_color.color_name != value
                    or any(getattr(option.product_color, k) != v for k, v in identity.items() if k in color)):
                raise ValidationError({"product_color_id": "颜色标识与色卡、色号或颜色名不一致，请重新选择。"})
            return option
        else:
            option = options.filter(product_color_id=None, value=value, color_card=identity["color_card"],
                                    color_code=identity["color_code"]).first()
            return option
    else:
        return options.filter(value=value).first()


def require_catalog_attribute(catalog, scope, key, value, *, parent_value=None, color=None):
    option = find_catalog_attribute(catalog, scope, key, value, parent_value=parent_value, color=color)
    if option is None:
        raise ValidationError({key: "请选择当前品名已维护的有效属性值。"})
    return option


def require_catalog_unit(catalog, scope, *, unit_id=None, unit_name=None):
    query = catalog.allowed_units.filter(Q(unit__catalog_owner__isnull=True) | Q(unit__catalog_owner=catalog),
                                        scope=scope, archived_at__isnull=True,
                                        unit__status="ACTIVE", unit__archived_at__isnull=True)
    option = query.select_related("unit").filter(**({"unit_id": unit_id} if unit_id else {"unit__unit_name": unit_name})).first()
    if option is None:
        raise ValidationError({"unit_id": "请选择当前品名与属性组的有效单位。"})
    return option.unit


def catalog_options(*, include_units=False):
    return {
        "categories": CATEGORIES, "spray_fields": SPRAY_FIELDS,
        "units": [{"id": str(unit.pk), "unit_name": unit.unit_name} for unit in
                  ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).order_by("unit_name", "pk")] if include_units else [],
        "warehouses": [
            {"id": str(row.pk), "warehouse_number": row.warehouse_number,
             "warehouse_name": row.warehouse_name, "warehouse_type": row.warehouse_type}
            for row in Warehouse.objects.filter(status="ACTIVE").order_by("warehouse_number", "id")
        ],
    }
