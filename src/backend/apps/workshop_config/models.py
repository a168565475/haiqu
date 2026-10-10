from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import TimeStampedModel

from .constants import FIXED_WORKSHOP_CHOICES, FIXED_WORKSHOP_NAMES


class RecordStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "启用"
    INACTIVE = "INACTIVE", "停用"


class WorkshopEmployeeStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "在职"
    LEFT = "LEFT", "离职"


class CraftType(models.TextChoices):
    INTERNAL = "INTERNAL", "厂内"
    EXTERNAL = "EXTERNAL", "厂外"


class OutsourcingCode(models.TextChoices):
    POWDER_COATING = "POWDER_COATING", "喷塑"
    SCREEN_PRINTING = "SCREEN_PRINTING", "丝印"
    CUTTING = "CUTTING", "裁剪"
    SEWING = "SEWING", "车缝"


class PlanCategory(models.TextChoices):
    METAL = "METAL", "金工计划"
    CUTTING = "CUTTING", "裁剪计划"
    SEWING = "SEWING", "车缝计划"
    ASSEMBLY = "ASSEMBLY", "装配计划"


class NoPhysicalDeleteModel(TimeStampedModel):
    class Meta:
        abstract = True

    def delete(self, *args, **kwargs):
        raise ValidationError("配置资料不允许物理删除，请使用停用状态。")


class Workshop(NoPhysicalDeleteModel):
    name = models.CharField(max_length=100, unique=True, choices=FIXED_WORKSHOP_CHOICES)
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE)
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_workshop_config_workshops",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_workshop_config_workshops",
    )

    class Meta:
        db_table = "workshop_config_workshop"
        ordering = ["name", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=RecordStatus.values), name="workshop_status_valid"),
            models.CheckConstraint(condition=Q(name__in=FIXED_WORKSHOP_NAMES), name="workshop_name_fixed"),
            models.CheckConstraint(condition=Q(status=RecordStatus.ACTIVE), name="workshop_always_active"),
        ]
        indexes = [models.Index(fields=["status", "name"], name="workshop_status_name_idx")]

    def __str__(self):
        return self.name


class WorkshopEmployee(NoPhysicalDeleteModel):
    workshop = models.ForeignKey(Workshop, on_delete=models.PROTECT, related_name="employees")
    position = models.CharField(max_length=100)
    name = models.CharField(max_length=100)
    is_supervisor = models.BooleanField()
    status = models.CharField(
        max_length=20,
        choices=WorkshopEmployeeStatus.choices,
        default=WorkshopEmployeeStatus.ACTIVE,
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_workshop_config_employees",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_workshop_config_employees",
    )

    class Meta:
        db_table = "workshop_config_employee"
        ordering = ["workshop__name", "position", "name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["workshop", "position", "name"], name="workshop_employee_business_unique"),
            models.CheckConstraint(
                condition=Q(status__in=WorkshopEmployeeStatus.values),
                name="workshop_employee_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["workshop", "status", "is_supervisor"], name="workshop_emp_lookup_idx"),
            models.Index(fields=["name"], name="workshop_emp_name_idx"),
        ]

    def __str__(self):
        return f"{self.workshop.name} - {self.position} - {self.name}"


class Craft(NoPhysicalDeleteModel):
    craft_type = models.CharField(max_length=20, choices=CraftType.choices)
    workshop = models.ForeignKey(
        Workshop,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="crafts",
    )
    name = models.CharField(max_length=100)
    plan_category = models.CharField(max_length=20, choices=PlanCategory.choices, null=True, blank=True)
    outsourcing_code = models.CharField(max_length=30, choices=OutsourcingCode.choices, null=True, blank=True)
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE)
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_workshop_config_crafts",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_workshop_config_crafts",
    )

    class Meta:
        db_table = "workshop_config_craft"
        ordering = ["craft_type", "name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["craft_type", "name"], name="workshop_craft_type_name_unique"),
            models.CheckConstraint(condition=Q(craft_type__in=CraftType.values), name="workshop_craft_type_valid"),
            models.CheckConstraint(condition=Q(status__in=RecordStatus.values), name="workshop_craft_status_valid"),
            models.CheckConstraint(
                condition=Q(plan_category__isnull=True) | Q(craft_type=CraftType.INTERNAL),
                name="workshop_craft_plan_internal",
            ),
            models.UniqueConstraint(
                fields=["plan_category"],
                condition=Q(plan_category__isnull=False),
                name="workshop_craft_plan_unique",
            ),
            models.UniqueConstraint(
                fields=["outsourcing_code"],
                condition=Q(outsourcing_code__isnull=False),
                name="workshop_craft_outsourcing_unique",
            ),
            models.CheckConstraint(
                condition=Q(outsourcing_code__isnull=True) | Q(craft_type=CraftType.EXTERNAL),
                name="workshop_craft_outsourcing_external",
            ),
            models.CheckConstraint(
                condition=(Q(craft_type=CraftType.INTERNAL, workshop__isnull=False) | Q(craft_type=CraftType.EXTERNAL, workshop__isnull=True)),
                name="workshop_craft_scope_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["craft_type", "status", "name"], name="workshop_craft_lookup_idx"),
            models.Index(fields=["workshop", "status"], name="workshop_craft_parent_idx"),
        ]

    def clean(self):
        super().clean()
        if self.craft_type == CraftType.INTERNAL and self.workshop_id is None:
            raise ValidationError({"workshop": "厂内工艺必须选择车间。"})
        if self.craft_type == CraftType.EXTERNAL and self.workshop_id is not None:
            raise ValidationError({"workshop": "厂外工艺不能填写车间。"})
        if self.craft_type == CraftType.EXTERNAL and self.plan_category is not None:
            raise ValidationError({"plan_category": "厂外工艺不能映射厂内计划。"})

    def __str__(self):
        return f"{self.get_craft_type_display()} - {self.name}"


class Operation(NoPhysicalDeleteModel):
    operation_number = models.CharField(max_length=50, unique=True)
    product_name = models.CharField(max_length=200, blank=True)
    craft = models.ForeignKey(Craft, on_delete=models.PROTECT, related_name="operations")
    reporting_unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="workshop_operations",
    )
    name = models.CharField(max_length=150)
    status = models.CharField(max_length=20, choices=RecordStatus.choices, default=RecordStatus.ACTIVE)
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="created_workshop_config_operations",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="updated_workshop_config_operations",
    )

    class Meta:
        db_table = "workshop_config_operation"
        ordering = ["operation_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["product_name", "craft", "name"], name="workshop_operation_business_unique"),
            models.CheckConstraint(condition=Q(status__in=RecordStatus.values), name="workshop_operation_status_valid"),
        ]
        indexes = [
            models.Index(fields=["craft", "status"], name="workshop_operation_craft_idx"),
            models.Index(fields=["product_name", "name"], name="workshop_operation_name_idx"),
        ]

    def __str__(self):
        return f"{self.operation_number} - {self.name}"
