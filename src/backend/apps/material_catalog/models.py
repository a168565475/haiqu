from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel

from .definitions import CATEGORY_CHOICES, TEMPLATE_CHOICES


class MaterialScope(models.TextChoices):
    BASE = "BASE", "基础属性"
    SPRAY = "SPRAY", "喷塑属性"


class MaterialCatalog(ArchivableModel):
    category_key = models.CharField(max_length=30, choices=CATEGORY_CHOICES)
    template_key = models.CharField(max_length=30, choices=TEMPLATE_CHOICES)
    name = models.CharField(max_length=200)
    spray_enabled = models.BooleanField(default=False)

    class Meta:
        db_table = "material_catalog"
        ordering = ["name", "id"]
        default_permissions = ("add", "change", "view")
        constraints = [
            models.UniqueConstraint(fields=["category_key", "name"], name="mat_catalog_category_name_uniq"),
            models.CheckConstraint(condition=~Q(name=""), name="mat_catalog_name_not_empty"),
            models.CheckConstraint(
                condition=(Q(category_key="TUBE", template_key="TUBE")
                    | Q(category_key="FABRIC", template_key="FABRIC")
                    | Q(category_key="HARDWARE", template_key="HARDWARE")
                    | Q(category_key="PLASTIC", template_key="PLASTIC")
                    | Q(category_key="PACKAGING", template_key__in=["CARTON", "BAG", "PACKAGING_GENERAL"])
                    | Q(category_key="AUXILIARY", template_key__in=["TAPE", "COTTON", "AUXILIARY_GENERAL"])
                    | Q(category_key="FABRIC_SEMI", template_key="FABRIC_SEMI")),
                name="mat_catalog_template_valid",
            ),
            models.CheckConstraint(
                condition=Q(spray_enabled=False) | Q(category_key__in=["TUBE", "HARDWARE"]),
                name="mat_catalog_spray_valid",
            ),
        ]


class MaterialAttributeValue(ArchivableModel):
    catalog = models.ForeignKey(MaterialCatalog, on_delete=models.PROTECT, related_name="attribute_values")
    scope = models.CharField(max_length=10, choices=MaterialScope.choices)
    field_key = models.CharField(max_length=40)
    value = models.CharField(max_length=300)
    parent = models.ForeignKey("self", null=True, blank=True, on_delete=models.PROTECT, related_name="dimensions")

    class Meta:
        db_table = "material_catalog_attribute_value"
        ordering = ["created_at", "id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(
                fields=["catalog", "scope", "field_key", "value", "parent"],
                nulls_distinct=False, name="mat_catalog_value_uniq",
            ),
            models.CheckConstraint(condition=Q(scope__in=MaterialScope.values), name="mat_catalog_value_scope_valid"),
            models.CheckConstraint(condition=~Q(value=""), name="mat_catalog_value_not_empty"),
            models.CheckConstraint(
                condition=(Q(field_key="section_size", scope="BASE", parent__isnull=False)
                    | (~Q(field_key="section_size") & Q(parent__isnull=True))),
                name="mat_catalog_parent_shape_valid",
            ),
        ]


class MaterialAllowedUnit(ArchivableModel):
    catalog = models.ForeignKey(MaterialCatalog, on_delete=models.PROTECT, related_name="allowed_units")
    scope = models.CharField(max_length=10, choices=MaterialScope.choices)
    unit = models.ForeignKey("reference_data.ProductionUnit", on_delete=models.PROTECT, related_name="material_catalog_options")

    class Meta:
        db_table = "material_catalog_allowed_unit"
        ordering = ["created_at", "id"]
        default_permissions = ()
        constraints = [
            models.UniqueConstraint(fields=["catalog", "scope", "unit"], name="mat_catalog_unit_uniq"),
            models.CheckConstraint(condition=Q(scope__in=MaterialScope.values), name="mat_catalog_unit_scope_valid"),
        ]
