"""整品名草稿统一保存；每条产品保留独立身份和属性。"""
from django.db import IntegrityError, transaction
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import etag_for_instance, require_matching_etag

from . import selectors, services
from .models import ProductCatalog, ProductCatalogColor, ProductCatalogName


def _check_external_references(instance, *, owned_relations=()):
    for relation in instance._meta.related_objects:
        model, field = relation.related_model, relation.field.name
        if (model, field) in owned_relations:
            continue
        if model._base_manager.filter(**{field: instance.pk}).exists():
            raise ValidationError({"delete_product_ids":
                f"{instance._meta.verbose_name}已被{model._meta.verbose_name}引用，不能删除。"})


def _check_product_delete(product):
    _check_external_references(product, owned_relations=((ProductCatalogColor, "product"),))
    for color in product.colors.all():
        _check_external_references(color)


def _delete_product(product, request):
    before = selectors.product_detail(product)
    product_id = product.pk
    product.colors.all().delete()
    product.delete()
    # delete() 会清空实例主键，审计仍必须记录原产品身份。
    product.pk = product_id
    services._audit(product, "DELETED", before, None, request)


def _replace_colors(product, values, request):
    existing = {color.value: color for color in product.colors.all()}
    now = timezone.now()
    for value, color in existing.items():
        if value in values and color.archived_at is not None:
            color.archived_at = None
            color.archived_by_employee = None
            color.archive_reason = ""
            color.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
        elif value not in values and color.archived_at is None:
            color.archived_at = now
            color.archived_by_employee = getattr(request, "employee", None)
            color.archive_reason = "从产品管理移除颜色"
            color.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
    for value in values:
        if value not in existing:
            ProductCatalogColor.objects.create(product=product, value=value)


def _write_product(name, data, request, *, product=None):
    fields = {key: value for key, value in data.items() if key not in {"id", "colors"}}
    services.validate_unit(fields.get("unit", product.unit if product else ""), previous=product.unit if product else None)
    before = selectors.product_detail(product) if product else None
    if product is None:
        product = ProductCatalog.objects.create(name=name, **fields)
        colors = data.get("colors", ["无颜色"])
    else:
        for key, value in fields.items():
            setattr(product, key, value)
        product.save(update_fields=[*fields, "updated_at"])
        colors = data.get("colors")
    if colors is not None:
        _replace_colors(product, colors, request)
    services._audit(product, "UPDATED" if before else "CREATED", before, selectors.product_detail(product), request)


@transaction.atomic
def read_editor(*, name_id):
    name = services.locked_name(name_id)
    return selectors.editor_detail(name), etag_for_instance(name)


def create_editor(*, data, request):
    try:
        with transaction.atomic():
            name_data, _ = services.create_name(data={"category_id": data["category_id"], "name": data["name"]}, request=request)
            name = services.locked_name(name_data["id"])
            for row in data.get("products", []):
                _write_product(name, row, request)
            name.save(update_fields=["updated_at"])
            return selectors.editor_detail(name), etag_for_instance(name)
    except IntegrityError as exc:
        services._name_conflict(exc)


def save_editor(*, name_id, data, request):
    try:
        with transaction.atomic():
            name = services.locked_name(name_id)
            require_matching_etag(request, name)
            before = selectors.name_detail(name)
            products = {row.pk: row for row in ProductCatalog.objects.select_for_update().filter(
                name=name, archived_at__isnull=True).order_by("id")}
            submitted = data.get("products", [])
            deleted_ids = data.get("delete_product_ids", [])
            submitted_ids = {row["id"] for row in submitted if "id" in row}
            if not (submitted_ids | set(deleted_ids)).issubset(products):
                raise ValidationError({"products": "提交的产品不存在、已删除或不属于当前品名。"})
            # 整批预检后再写；任一引用/单位/名称校验失败，所有修改都回滚。
            for product_id in deleted_ids:
                _check_product_delete(products[product_id])
            for row in submitted:
                product = products.get(row.get("id"))
                services.validate_unit(row.get("unit", product.unit if product else ""), previous=product.unit if product else None)
            renamed = name.name != data["name"]
            name.name = data["name"]
            name.save(update_fields=["name", "updated_at"])
            if renamed:
                name.products.update(updated_at=timezone.now())
            for product_id in deleted_ids:
                _delete_product(products[product_id], request)
            for row in submitted:
                _write_product(name, row, request, product=products.get(row.get("id")))
            after = selectors.editor_detail(name)
            services._audit(name, "SAVED", before, after["name"], request, object_type="PRODUCT_CATALOG_NAME")
            return after, etag_for_instance(name)
    except IntegrityError as exc:
        services._name_conflict(exc)


@transaction.atomic
def delete_name(*, name_id, request):
    name = services.locked_name(name_id)
    require_matching_etag(request, name)
    _check_external_references(name, owned_relations=((ProductCatalog, "name"),))
    products = list(ProductCatalog.objects.select_for_update().filter(name=name).order_by("id"))
    for product in products:
        _check_product_delete(product)
    before = selectors.name_detail(name)
    before["deleted_product_count"] = len(products)
    for product in products:
        _delete_product(product, request)
    name_id = name.pk
    name.delete()
    name.pk = name_id
    services._audit(name, "DELETED", before, None, request, object_type="PRODUCT_CATALOG_NAME")
