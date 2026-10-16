from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel, TimeStampedModel


class ProductCatalogCategory(ArchivableModel):
    name = models.CharField(max_length=150, unique=True)
    sort_order = models.PositiveIntegerField(default=0)

    class Meta:
        db_table = "product_catalog_category"
        ordering = ["sort_order", "name", "id"]
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=~Q(name=""), name="prod_cat_category_name_nonempty")]


class ProductCatalogName(ArchivableModel):
    category = models.ForeignKey(ProductCatalogCategory, on_delete=models.PROTECT, related_name="names")
    name = models.CharField(max_length=200)

    class Meta:
        db_table = "product_catalog_name"
        ordering = ["name", "id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["category", "name"], name="prod_cat_category_name_uniq"),
            models.CheckConstraint(condition=~Q(name=""), name="prod_cat_name_nonempty"),
        ]


class ProductCatalogImport(TimeStampedModel):
    filename = models.CharField(max_length=255)
    sha256 = models.CharField(max_length=64)
    sheet = models.CharField(max_length=255)
    source_bytes = models.BinaryField()
    row_count = models.PositiveIntegerField()

    class Meta:
        db_table = "product_catalog_import"
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["filename", "sha256", "sheet"], name="prod_cat_import_source_uniq"),
            models.CheckConstraint(condition=~Q(filename="") & ~Q(sheet="") & Q(sha256__regex=r"^[0-9a-f]{64}$"), name="prod_cat_import_source_valid"),
            models.CheckConstraint(condition=Q(row_count__gt=0), name="prod_cat_import_rows_positive"),
        ]


class ProductCatalog(ArchivableModel):
    name = models.ForeignKey(ProductCatalogName, on_delete=models.PROTECT, related_name="products")
    product_code = models.CharField(max_length=100, blank=True)
    item_number = models.CharField(max_length=100, blank=True)
    specification = models.CharField(max_length=300, blank=True)
    unit = models.CharField(max_length=80, blank=True)
    scale = models.CharField(max_length=100, blank=True)
    source_import = models.ForeignKey(ProductCatalogImport, null=True, blank=True, on_delete=models.PROTECT, related_name="products")
    source_filename = models.CharField(max_length=255, blank=True)
    source_sha256 = models.CharField(max_length=64, blank=True)
    source_sheet = models.CharField(max_length=255, blank=True)
    source_row = models.PositiveIntegerField(null=True, blank=True)
    source_raw_fields = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "product_catalog"
        ordering = ["created_at", "id"]
        default_permissions = ("add", "change", "view")
        constraints = [
            models.UniqueConstraint(fields=["source_filename", "source_sha256", "source_sheet", "source_row"], condition=~Q(source_sha256=""), name="prod_cat_source_row_uniq"),
            models.CheckConstraint(
                condition=(Q(source_import__isnull=True, source_filename="", source_sha256="", source_sheet="", source_row__isnull=True, source_raw_fields={})
                    | (Q(source_import__isnull=False, source_sha256__regex=r"^[0-9a-f]{64}$", source_row__gt=0, source_row__isnull=False) & ~Q(source_filename="") & ~Q(source_sheet=""))),
                name="prod_cat_source_complete",
            ),
        ]


class ProductCatalogColor(ArchivableModel):
    product = models.ForeignKey(ProductCatalog, on_delete=models.PROTECT, related_name="colors")
    value = models.CharField(max_length=200)

    class Meta:
        db_table = "product_catalog_color"
        ordering = ["created_at", "id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["product", "value"], name="prod_cat_color_value_uniq"),
            models.CheckConstraint(condition=~Q(value=""), name="prod_cat_color_value_nonempty"),
        ]
