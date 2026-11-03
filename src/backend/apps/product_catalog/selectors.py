from django.db.models import Count, Prefetch, Q

from apps.reference_data.models import ProductionUnit

from .models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogName


def active_products():
    return ProductCatalog.objects.filter(archived_at__isnull=True, name__archived_at__isnull=True, name__category__archived_at__isnull=True)


def product_list(*, category_id=None, name_id=None, q=""):
    queryset = active_products().select_related("name__category").prefetch_related(
        Prefetch("colors", queryset=ProductCatalogColor.objects.filter(archived_at__isnull=True), to_attr="active_colors")
    )
    if category_id:
        queryset = queryset.filter(name__category_id=category_id)
    if name_id:
        queryset = queryset.filter(name_id=name_id)
    if q:
        queryset = queryset.filter(Q(name__name__icontains=q) | Q(product_code__icontains=q) | Q(item_number__icontains=q) | Q(specification__icontains=q))
    return queryset


def name_list(*, category_id=None, q=""):
    queryset = ProductCatalogName.objects.filter(archived_at__isnull=True, category__archived_at__isnull=True).select_related("category").annotate(
        active_product_count=Count("products", filter=Q(products__archived_at__isnull=True))
    )
    if category_id:
        queryset = queryset.filter(category_id=category_id)
    if q:
        queryset = queryset.filter(name__icontains=q)
    return queryset


def name_detail(name):
    count = getattr(name, "active_product_count", None)
    return {
        "id": str(name.pk), "category_id": str(name.category_id), "category_name": name.category.name,
        "name": name.name, "product_count": count if count is not None else name.products.filter(archived_at__isnull=True).count(),
        "updated_at": name.updated_at.isoformat(),
    }


def product_summary(product):
    colors = getattr(product, "active_colors", None)
    if colors is None:
        colors = product.colors.filter(archived_at__isnull=True)
    return {
        "id": str(product.pk), "name_id": str(product.name_id), "name": product.name.name,
        "category_id": str(product.name.category_id), "category_name": product.name.category.name,
        "product_code": product.product_code, "item_number": product.item_number,
        "specification": product.specification, "unit": product.unit, "scale": product.scale,
        "materials": product.materials, "thicknesses": product.thicknesses,
        "colors": [{"id": str(color.pk), "value": color.value} for color in colors],
        "updated_at": product.updated_at.isoformat(),
    }


def product_detail(product):
    return {
        **product_summary(product), "created_at": product.created_at.isoformat(),
        "source": {"filename": product.source_filename, "sha256": product.source_sha256,
                   "sheet": product.source_sheet, "row": product.source_row, "raw_fields": product.source_raw_fields} if product.source_import_id else None,
    }


def catalog_options():
    products = active_products()
    categories = ProductCatalogCategory.objects.filter(archived_at__isnull=True).annotate(
        name_count=Count("names", filter=Q(names__archived_at__isnull=True))
    ).order_by("sort_order", "name", "id")
    return {
        "categories": [{"id": str(row.pk), "name": row.name, "name_count": row.name_count} for row in categories],
        "units": list(ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True).values_list("unit_name", flat=True)),
        "scales": list(products.exclude(scale="").order_by("scale").values_list("scale", flat=True).distinct()),
    }


def editor_detail(name):
    return {"name": name_detail(name), "products": [product_summary(row) for row in product_list(name_id=name.pk)]}


def selection_options():
    units = {row.unit_name: row for row in ProductionUnit.objects.filter(status="ACTIVE", archived_at__isnull=True)}
    products = []
    for product in product_list():
        unit = units.get(product.unit)
        products.append({**product_summary(product), "catalog_version": product.updated_at.isoformat(),
                         "unit_id": str(unit.pk) if unit else None, "unit_code": unit.unit_code if unit else ""})
    return {
        "categories": [{"id": str(row.pk), "name": row.name} for row in ProductCatalogCategory.objects.filter(archived_at__isnull=True)],
        "names": [{"id": str(row.pk), "category_id": str(row.category_id), "name": row.name} for row in name_list()],
        "products": products,
        "units": [{"id": str(unit.pk), "unit_name": unit.unit_name, "unit_code": unit.unit_code} for unit in units.values()],
    }
