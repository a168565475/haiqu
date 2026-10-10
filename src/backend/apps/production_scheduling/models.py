from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import TimeStampedModel, uppercase_code_validator
from apps.workshop_config.models import CraftType, PlanCategory


class ScheduleStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "有效"
    VOID = "VOID", "已作废"


class ProductionSchedule(TimeStampedModel):
    schedule_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    production_task = models.ForeignKey(
        "production_tasks.ProductionTask", on_delete=models.PROTECT, related_name="production_schedules"
    )
    record_status = models.CharField(max_length=20, choices=ScheduleStatus.choices, default=ScheduleStatus.ACTIVE)
    version = models.PositiveIntegerField(default=1)
    source_snapshot = models.JSONField(default=dict)
    source_revision_hash = models.CharField(max_length=64)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="created_production_schedules"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="updated_production_schedules"
    )
    void_reason = models.TextField(blank=True)
    voided_at = models.DateTimeField(null=True, blank=True)
    voided_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="voided_production_schedules",
    )

    class Meta:
        db_table = "production_schedule"
        ordering = ["-created_at", "-id"]
        permissions = [
            ("view_all_productionschedule", "可查看全部生产排产"),
            ("void_productionschedule", "可作废生产排产"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["production_task"], condition=Q(record_status=ScheduleStatus.ACTIVE),
                name="prod_sched_task_active_uniq",
            ),
            models.CheckConstraint(condition=Q(record_status__in=ScheduleStatus.values), name="prod_sched_status_valid"),
            models.CheckConstraint(condition=Q(version__gt=0), name="prod_sched_version_positive"),
            models.CheckConstraint(
                condition=(
                    Q(record_status=ScheduleStatus.ACTIVE, void_reason="", voided_at__isnull=True, voided_by_employee__isnull=True)
                    | Q(record_status=ScheduleStatus.VOID, voided_at__isnull=False, voided_by_employee__isnull=False) & ~Q(void_reason="")
                ),
                name="prod_sched_void_fields_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["record_status", "-created_at"], name="prod_sched_status_created_idx"),
            models.Index(fields=["production_task", "record_status"], name="prod_sched_task_status_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("排产计划不允许物理删除，请使用整单作废。")


class ProductionScheduleProduct(TimeStampedModel):
    schedule = models.ForeignKey(ProductionSchedule, on_delete=models.PROTECT, related_name="products")
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct", on_delete=models.PROTECT, related_name="schedule_products"
    )
    line_number = models.PositiveIntegerField()
    planned_quantity = models.PositiveBigIntegerField()
    source_quantity_snapshot = models.PositiveBigIntegerField()
    unit = models.ForeignKey("reference_data.ProductionUnit", on_delete=models.PROTECT, related_name="schedule_products")
    unit_name_snapshot = models.CharField(max_length=50)
    image_file = models.ForeignKey(
        "files.BusinessFile", null=True, blank=True, on_delete=models.PROTECT, related_name="schedule_products"
    )
    material_inbound_date = models.DateField()
    metal_return_date = models.DateField()
    sewing_return_date = models.DateField()
    finished_inbound_date = models.DateField()
    product_snapshot = models.JSONField(default=dict)
    source_revision_hash = models.CharField(max_length=64)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="removed_production_schedule_products",
    )

    class Meta:
        db_table = "production_schedule_product"
        ordering = ["schedule", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule", "product_line"], condition=Q(removed_at__isnull=True),
                name="prod_sched_product_active_uniq",
            ),
            models.UniqueConstraint(
                fields=["schedule", "line_number"], condition=Q(removed_at__isnull=True),
                name="prod_sched_line_active_uniq",
            ),
            models.CheckConstraint(condition=Q(line_number__gt=0), name="prod_sched_line_positive"),
            models.CheckConstraint(condition=Q(planned_quantity__gt=0), name="prod_sched_qty_positive"),
            models.CheckConstraint(condition=Q(source_quantity_snapshot__gt=0), name="prod_sched_source_qty_positive"),
            models.CheckConstraint(
                condition=Q(planned_quantity__lte=F("source_quantity_snapshot")),
                name="prod_sched_qty_within_source",
            ),
            models.CheckConstraint(
                condition=(Q(removed_at__isnull=True, removed_by_employee__isnull=True) | Q(removed_at__isnull=False, removed_by_employee__isnull=False)),
                name="prod_sched_removed_fields_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["schedule", "removed_at", "line_number"], name="prod_sched_product_lookup_idx"),
            models.Index(fields=["product_line", "removed_at"], name="prod_sched_source_lookup_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("排产产品不允许物理删除，请保留移除记录。")


class ProductionScheduleProductCraft(TimeStampedModel):
    schedule_product = models.ForeignKey(
        ProductionScheduleProduct, on_delete=models.PROTECT, related_name="crafts"
    )
    craft = models.ForeignKey(
        "workshop_config.Craft", on_delete=models.PROTECT, related_name="schedule_product_links"
    )
    craft_type_snapshot = models.CharField(max_length=20, choices=CraftType.choices)
    craft_name_snapshot = models.CharField(max_length=100)
    plan_category = models.CharField(max_length=20, choices=PlanCategory.choices, null=True, blank=True)
    removed_at = models.DateTimeField(null=True, blank=True)
    removed_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="removed_production_schedule_crafts",
    )

    class Meta:
        db_table = "production_schedule_product_craft"
        ordering = ["schedule_product", "craft_type_snapshot", "craft_name_snapshot", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule_product", "craft"], condition=Q(removed_at__isnull=True),
                name="prod_sched_craft_active_uniq",
            ),
            models.CheckConstraint(condition=Q(craft_type_snapshot__in=CraftType.values), name="prod_sched_craft_type_valid"),
            models.CheckConstraint(
                condition=Q(plan_category__isnull=True) | Q(craft_type_snapshot=CraftType.INTERNAL),
                name="prod_sched_craft_plan_internal",
            ),
            models.CheckConstraint(
                condition=(Q(removed_at__isnull=True, removed_by_employee__isnull=True) | Q(removed_at__isnull=False, removed_by_employee__isnull=False)),
                name="prod_sched_craft_removed_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["plan_category", "craft_type_snapshot", "removed_at"],
                name="prod_sched_craft_plan_idx",
            ),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("排产工艺不允许物理删除，请保留移除记录。")
