from apps.reference_data.models import ProductionUnit

from .definitions import CATEGORIES, SPRAY_FIELDS
from .models import MaterialCatalog


def catalog_list(*, category="", query=""):
    queryset = MaterialCatalog.objects.filter(archived_at__isnull=True)
    if category:
        queryset = queryset.filter(category_key=category)
    if query:
        queryset = queryset.filter(name__icontains=query)
    return queryset.order_by("name", "id")


def catalog_summary(catalog):
    return {
        "id": str(catalog.pk), "category_key": catalog.category_key,
        "template_key": catalog.template_key, "name": catalog.name,
        "spray_enabled": catalog.spray_enabled, "updated_at": catalog.updated_at.isoformat(),
    }


def catalog_detail(catalog):
    return {
        **catalog_summary(catalog),
        "values": [
            {"id": str(row.pk), "scope": row.scope, "field_key": row.field_key,
             "value": row.value, "parent_id": str(row.parent_id) if row.parent_id else None}
            for row in catalog.attribute_values.filter(archived_at__isnull=True)
        ],
        "units": [
            {"id": str(row.pk), "scope": row.scope, "unit_id": str(row.unit_id), "unit_name": row.unit.unit_name}
            for row in catalog.allowed_units.filter(archived_at__isnull=True).select_related("unit")
        ],
    }


def catalog_options():
    return {
        "categories": CATEGORIES, "spray_fields": SPRAY_FIELDS,
        "units": [
            {"id": str(row.pk), "unit_name": row.unit_name}
            for row in ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).order_by("sort_order", "unit_name", "id")
        ],
    }
