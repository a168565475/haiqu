from collections.abc import Mapping

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.audit import write_audit_log

from .api.serializers import ProductCreateSerializer
from .models import ProductCatalog, ProductCatalogCategory, ProductCatalogColor, ProductCatalogImport, ProductCatalogName
from .selectors import name_detail, product_detail


def _audit(instance, action, before, after, request, *, object_type="PRODUCT_CATALOG"):
    write_audit_log(object_type=object_type, object_id=instance.pk, action=action,
                    actor_employee=getattr(request, "employee", None), before_data=before, after_data=after, request=request)


def _name_conflict(exc):
    if getattr(getattr(exc.__cause__, "diag", None), "constraint_name", None) == "prod_cat_category_name_uniq":
        raise ValidationError({"name": "该类别下已存在相同完整品名，不能自动合并。"}) from exc
    raise exc


def create_name(*, data, request):
    try:
        with transaction.atomic():
            category = get_object_or_404(ProductCatalogCategory, pk=data["category_id"], archived_at__isnull=True)
            name = ProductCatalogName.objects.create(category=category, name=data["name"])
            after = name_detail(name)
            _audit(name, "CREATED", None, after, request, object_type="PRODUCT_CATALOG_NAME")
            return after, etag_for_instance(name)
    except IntegrityError as exc:
        _name_conflict(exc)


def rename_name(*, name_id, value, request):
    try:
        with transaction.atomic():
            name = get_object_or_404(ProductCatalogName.objects.select_for_update(of=("self",)).select_related("category"), pk=name_id, archived_at__isnull=True, category__archived_at__isnull=True)
            require_matching_etag(request, name)
            before = name_detail(name)
            name.name = value
            name.save(update_fields=["name", "updated_at"])
            # 完整详情展示品名，改名后旧产品详情版本必须失效。
            name.products.update(updated_at=timezone.now())
            after = name_detail(name)
            _audit(name, "RENAMED", before, after, request, object_type="PRODUCT_CATALOG_NAME")
            return after, etag_for_instance(name)
    except IntegrityError as exc:
        _name_conflict(exc)


def _source_fields(source):
    if source is None:
        return {}
    required = {"filename", "sha256", "sheet", "row", "raw_fields", "import_id"}
    if not isinstance(source, Mapping) or set(source) != required:
        raise ValidationError({"source": "来源必须包含完整文件、工作表、原行及导入批次。"})
    if type(source["row"]) is not int or source["row"] < 1 or not isinstance(source["raw_fields"], dict):
        raise ValidationError({"source": "来源行必须是正整数，原始字段必须是对象。"})
    batch = ProductCatalogImport.objects.filter(pk=source["import_id"]).first()
    if batch is None or (batch.filename, batch.sha256, batch.sheet) != (source["filename"], source["sha256"], source["sheet"]):
        raise ValidationError({"source": "来源文件信息与保存的导入批次不一致。"})
    return {"source_import": batch, "source_filename": batch.filename, "source_sha256": batch.sha256,
            "source_sheet": batch.sheet, "source_row": source["row"], "source_raw_fields": source["raw_fields"]}


@transaction.atomic
def create_product_record(*, data, source=None, request=None):
    """页面和受控导入共享创建规则；业务字段相同也始终创建独立身份。"""
    serializer = ProductCreateSerializer(data=data)
    serializer.is_valid(raise_exception=True)
    values = dict(serializer.validated_data)
    name_id = values.pop("name_id")
    name = ProductCatalogName.objects.select_for_update(of=("self",)).select_related("category").filter(
        pk=name_id, archived_at__isnull=True, category__archived_at__isnull=True
    ).first()
    if name is None:
        raise ValidationError({"name_id": "完整品名不存在或已归档。"})
    product = ProductCatalog.objects.create(name=name, **values, **_source_fields(source))
    ProductCatalogColor.objects.create(product=product, value="无颜色")
    # 名称详情含产品数量，创建产品也刷新该详情的版本。
    name.save(update_fields=["updated_at"])
    _audit(product, "CREATED", None, product_detail(product), request)
    return product


def create_product(*, data, request):
    with transaction.atomic():
        product = create_product_record(data=data, request=request)
        return product_detail(product), etag_for_instance(product)


def _locked_product(product_id, request):
    product = get_object_or_404(ProductCatalog.objects.select_for_update(of=("self",)),
                               pk=product_id, archived_at__isnull=True, name__archived_at__isnull=True, name__category__archived_at__isnull=True)
    require_matching_etag(request, product)
    return product


def _finish_product(product, before, action, request, *, fields=()):
    product.save(update_fields=[*fields, "updated_at"])
    after = product_detail(product)
    _audit(product, action, before, after, request)
    return after, etag_for_instance(product)


@transaction.atomic
def update_product(*, product_id, data, request):
    product = _locked_product(product_id, request)
    before = product_detail(product)
    for field, value in data.items():
        setattr(product, field, value)
    return _finish_product(product, before, "UPDATED", request, fields=data.keys())


@transaction.atomic
def add_color(*, product_id, value, request):
    product = _locked_product(product_id, request)
    before = product_detail(product)
    existing = product.colors.filter(value=value).first()
    if existing is not None:
        if existing.archived_at is None:
            raise ValidationError({"value": "该产品已包含此颜色。"})
        existing.archived_at = None
        existing.archived_by_employee = None
        existing.archive_reason = ""
        existing.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
        action = "COLOR_RESTORED"
    else:
        ProductCatalogColor.objects.create(product=product, value=value)
        action = "COLOR_ADDED"
    return _finish_product(product, before, action, request)


@transaction.atomic
def remove_color(*, product_id, color_id, request):
    product = _locked_product(product_id, request)
    color = get_object_or_404(ProductCatalogColor, pk=color_id, product=product, archived_at__isnull=True)
    before = product_detail(product)
    color.archived_at = timezone.now()
    color.archived_by_employee = getattr(request, "employee", None)
    color.archive_reason = "从产品管理移除颜色"
    color.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
    return _finish_product(product, before, "COLOR_REMOVED", request)
