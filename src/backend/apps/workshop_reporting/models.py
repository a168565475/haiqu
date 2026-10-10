from decimal import Decimal

from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DateRangeField, RangeOperators
from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Func, Q, Value

from apps.core.models import TimeStampedModel


class WageSchemeStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    PENDING_APPROVAL = "PENDING_APPROVAL", "待审批"
    APPROVED = "APPROVED", "已批准"
    RETURNED = "RETURNED", "已退回"
    SUPERSEDED = "SUPERSEDED", "已被替代"


class WageSchemeLineStatus(models.TextChoices):
    ACTIVE = "ACTIVE", "正常"
    VOID = "VOID", "作废"


class WorkCountingMode(models.TextChoices):
    ORDER = "ORDER", "按订单量"
    SET = "SET", "按套"
    PIECE = "PIECE", "按片"


class WorkshopPlanStatus(models.TextChoices):
    IN_PROGRESS = "IN_PROGRESS", "进行中"
    COMPLETED = "COMPLETED", "已完成"


class WageSchemeAction(models.TextChoices):
    CREATED = "CREATED", "创建"
    UPDATED = "UPDATED", "修改"
    SUBMITTED = "SUBMITTED", "送审"
    APPROVED = "APPROVED", "批准"
    RETURNED = "RETURNED", "退回"
    CHANGE_CREATED = "CHANGE_CREATED", "发起变更"


class WorkshopReportingScope(TimeStampedModel):
    employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="workshop_reporting_scopes"
    )
    workshop = models.ForeignKey(
        "workshop_config.Workshop", on_delete=models.PROTECT, related_name="reporting_scopes"
    )
    is_active = models.BooleanField(default=True)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="created_workshop_reporting_scopes"
    )

    class Meta:
        db_table = "workshop_reporting_scope"
        ordering = ["employee", "workshop"]
        constraints = [
            models.UniqueConstraint(fields=["employee", "workshop"], name="work_report_scope_unique"),
        ]
        indexes = [models.Index(fields=["employee", "is_active"], name="work_report_scope_emp_idx")]


class WageScheme(TimeStampedModel):
    scheme_number = models.CharField(max_length=50, unique=True)
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct", on_delete=models.PROTECT, related_name="wage_schemes"
    )
    workshop = models.ForeignKey(
        "workshop_config.Workshop", on_delete=models.PROTECT, related_name="wage_schemes"
    )
    scope_craft = models.ForeignKey(
        "workshop_config.Craft", on_delete=models.PROTECT, related_name="scoped_wage_schemes"
    )
    schedule_product = models.ForeignKey(
        "production_scheduling.ProductionScheduleProduct",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="wage_schemes",
    )
    status = models.CharField(max_length=24, choices=WageSchemeStatus.choices, default=WageSchemeStatus.DRAFT)
    version = models.PositiveIntegerField(default=1)
    revision = models.PositiveIntegerField(default=1)
    parent_scheme = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="change_versions"
    )
    history_source_scheme = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="referenced_versions"
    )
    effective_from = models.DateField(null=True, blank=True)
    effective_to = models.DateField(null=True, blank=True)
    product_name_snapshot = models.CharField(max_length=200)
    product_number_snapshot = models.CharField(max_length=100)
    product_specification_snapshot = models.CharField(max_length=300, blank=True)
    operation_product_name_snapshot = models.CharField(max_length=200)
    remark = models.TextField(blank=True)
    created_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="created_wage_schemes"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="updated_wage_schemes"
    )
    approved_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="approved_wage_schemes",
    )
    approved_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "workshop_wage_scheme"
        ordering = ["-created_at", "-id"]
        permissions = [
            ("submit_wagescheme", "可送审工价方案"),
            ("approve_wagescheme", "可审批工价方案"),
            ("view_all_wagescheme", "可查看全部车间工价方案"),
        ]
        constraints = [
            models.UniqueConstraint(
                fields=["parent_scheme", "version"], condition=Q(parent_scheme__isnull=False),
                name="wage_scheme_parent_version_unique",
            ),
            models.UniqueConstraint(
                fields=["product_line", "workshop", "scope_craft"], condition=Q(parent_scheme__isnull=True),
                name="wage_scheme_scope_root_unique",
            ),
            models.UniqueConstraint(
                fields=["parent_scheme"], condition=Q(parent_scheme__isnull=False),
                name="wage_scheme_parent_single_child",
            ),
            models.CheckConstraint(condition=Q(version__gt=0), name="wage_scheme_version_positive"),
            models.CheckConstraint(condition=Q(revision__gt=0), name="wage_scheme_revision_positive"),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_from__isnull=False),
                name="wage_scheme_to_requires_from",
            ),
            models.CheckConstraint(
                condition=Q(effective_to__isnull=True) | Q(effective_to__gte=F("effective_from")),
                name="wage_scheme_effective_range_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(status=WageSchemeStatus.APPROVED, effective_from__isnull=False, approved_at__isnull=False,
                      approved_by_employee__isnull=False)
                    | ~Q(status=WageSchemeStatus.APPROVED)
                ),
                name="wage_scheme_approved_fields_valid",
            ),
            ExclusionConstraint(
                name="wage_scheme_approved_scope_no_overlap",
                expressions=[
                    ("product_line", RangeOperators.EQUAL),
                    ("workshop", RangeOperators.EQUAL),
                    ("scope_craft", RangeOperators.EQUAL),
                    (
                        Func(
                            F("effective_from"), F("effective_to"), Value("[]"),
                            function="DATERANGE", output_field=DateRangeField(),
                        ),
                        RangeOperators.OVERLAPS,
                    ),
                ],
                condition=Q(status=WageSchemeStatus.APPROVED),
            ),
        ]
        indexes = [
            models.Index(fields=["product_line", "workshop", "status"], name="wage_scheme_scope_idx"),
            models.Index(fields=["status", "effective_from"], name="wage_scheme_effective_idx"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("工价方案不允许物理删除。")


class WageSchemeCraft(TimeStampedModel):
    scheme = models.ForeignKey(WageScheme, on_delete=models.PROTECT, related_name="scheme_crafts")
    craft = models.ForeignKey("workshop_config.Craft", on_delete=models.PROTECT, related_name="wage_scheme_links")

    class Meta:
        db_table = "workshop_wage_scheme_craft"
        constraints = [models.UniqueConstraint(fields=["scheme", "craft"], name="wage_scheme_craft_unique")]


class WorkItem(TimeStampedModel):
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct", on_delete=models.PROTECT, related_name="wage_work_items"
    )
    workshop = models.ForeignKey("workshop_config.Workshop", on_delete=models.PROTECT, related_name="wage_work_items")
    craft = models.ForeignKey("workshop_config.Craft", on_delete=models.PROTECT, related_name="wage_work_items")
    operation = models.ForeignKey("workshop_config.Operation", on_delete=models.PROTECT, related_name="wage_work_items")
    unit = models.ForeignKey(
        "reference_data.ProductionUnit", null=True, blank=True, on_delete=models.PROTECT,
        related_name="wage_work_items",
    )
    identity_key = models.CharField(max_length=64)
    display_name = models.CharField(max_length=200)
    bom_component_identity = models.UUIDField(null=True, blank=True)
    counting_mode = models.CharField(
        max_length=12, choices=WorkCountingMode.choices, default=WorkCountingMode.ORDER
    )

    class Meta:
        db_table = "workshop_work_item"
        ordering = ["product_line", "workshop", "display_name", "id"]
        constraints = [
            models.UniqueConstraint(fields=["product_line", "workshop", "identity_key"], name="work_item_identity_unique")
        ]


class WageSchemeLine(TimeStampedModel):
    scheme = models.ForeignKey(WageScheme, on_delete=models.PROTECT, related_name="lines")
    work_item = models.ForeignKey(WorkItem, on_delete=models.PROTECT, related_name="scheme_lines")
    line_number = models.PositiveIntegerField()
    display_name_snapshot = models.CharField(max_length=200)
    production_description = models.CharField(max_length=500, blank=True)
    craft_name_snapshot = models.CharField(max_length=100)
    operation_name_snapshot = models.CharField(max_length=150)
    operation_number_snapshot = models.CharField(max_length=50)
    unit_name_snapshot = models.CharField(max_length=80)
    bom_component_identity_snapshot = models.UUIDField(null=True, blank=True)
    counting_mode = models.CharField(
        max_length=12, choices=WorkCountingMode.choices, default=WorkCountingMode.ORDER
    )
    order_quantity_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    bom_sets_per_product_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    bom_pieces_per_set_snapshot = models.PositiveBigIntegerField(null=True, blank=True)
    required_quantity_snapshot = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    previous_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    revised_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    declared_price = models.DecimalField(
        max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0"))]
    )
    status = models.CharField(max_length=16, choices=WageSchemeLineStatus.choices, default=WageSchemeLineStatus.ACTIVE)
    note = models.CharField(max_length=500, blank=True)
    source_line = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.PROTECT, related_name="copied_lines"
    )

    class Meta:
        db_table = "workshop_wage_scheme_line"
        ordering = ["scheme", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["scheme", "line_number"], name="wage_scheme_line_number_unique"),
            models.UniqueConstraint(fields=["scheme", "work_item"], name="wage_scheme_work_item_unique"),
            models.CheckConstraint(condition=Q(line_number__gt=0), name="wage_scheme_line_positive"),
            models.CheckConstraint(condition=Q(declared_price__gte=0), name="wage_scheme_price_nonnegative"),
        ]


class WageSchemeEvent(TimeStampedModel):
    scheme = models.ForeignKey(WageScheme, on_delete=models.PROTECT, related_name="events")
    action = models.CharField(max_length=24, choices=WageSchemeAction.choices)
    scheme_revision = models.PositiveIntegerField()
    actor_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="wage_scheme_events"
    )
    comment = models.TextField(blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "workshop_wage_scheme_event"
        ordering = ["created_at", "id"]


class WorkReport(TimeStampedModel):
    report_number = models.CharField(max_length=50, unique=True)
    production_date = models.DateField()
    task_number_snapshot = models.CharField(max_length=50)
    order_number_snapshot = models.CharField(max_length=100)
    product_name_snapshot = models.CharField(max_length=200)
    product_number_snapshot = models.CharField(max_length=100)
    recorder_name_snapshot = models.CharField(max_length=150)
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct", on_delete=models.PROTECT, related_name="work_reports"
    )
    schedule_product = models.ForeignKey(
        "production_scheduling.ProductionScheduleProduct", on_delete=models.PROTECT, related_name="work_reports"
    )
    workshop = models.ForeignKey("workshop_config.Workshop", on_delete=models.PROTECT, related_name="work_reports")
    scheme = models.ForeignKey(WageScheme, on_delete=models.PROTECT, related_name="work_reports")
    scheme_version_snapshot = models.PositiveIntegerField()
    revision = models.PositiveIntegerField(default=1)
    recorder_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="recorded_work_reports"
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee", on_delete=models.PROTECT, related_name="updated_work_reports"
    )
    total_amount = models.DecimalField(max_digits=24, decimal_places=2)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    completed_plan = models.BooleanField(default=False)

    class Meta:
        db_table = "workshop_work_report"
        ordering = ["-production_date", "-created_at", "-id"]
        permissions = [
            ("view_all_workreport", "可查看全部车间报工"),
        ]
        indexes = [
            models.Index(fields=["production_date", "workshop"], name="work_report_day_scope_idx"),
            models.Index(fields=["product_line", "workshop"], name="work_report_product_idx"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(revision__gt=0), name="work_report_revision_positive"),
        ]

    def delete(self, *args, **kwargs):
        raise ValidationError("请通过报工删除服务填写原因并保留审计后删除。")


class WorkReportHistory(TimeStampedModel):
    """Independent request ledger; report deletion must never cascade here."""
    client_request_id = models.UUIDField(unique=True)
    report_id = models.UUIDField(unique=True)
    report_number = models.CharField(max_length=50)
    request_payload_hash = models.CharField(max_length=64)
    used_scheme_ids = models.JSONField(default=list)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by_employee_id = models.UUIDField(null=True, blank=True)
    deleted_by_name = models.CharField(max_length=150, blank=True)
    deletion_reason = models.CharField(max_length=1000, blank=True)
    deletion_snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "workshop_work_report_history"
        default_permissions = ()

    def delete(self, *args, **kwargs):
        raise ValidationError("报工请求历史与删除日志不允许删除。")


class WorkReportLine(TimeStampedModel):
    report = models.ForeignKey(WorkReport, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    scheme_line = models.ForeignKey(WageSchemeLine, on_delete=models.PROTECT, related_name="report_lines")
    work_item = models.ForeignKey(WorkItem, on_delete=models.PROTECT, related_name="report_lines")
    workshop_employee = models.ForeignKey(
        "workshop_config.WorkshopEmployee", on_delete=models.PROTECT, related_name="work_report_lines"
    )
    production_line = models.PositiveSmallIntegerField(null=True, blank=True)
    quantity = models.DecimalField(
        max_digits=18, decimal_places=4, validators=[MinValueValidator(Decimal("0.0001"))]
    )
    order_quantity_snapshot = models.PositiveBigIntegerField()
    required_quantity_snapshot = models.DecimalField(max_digits=24, decimal_places=4, null=True, blank=True)
    unit_price_snapshot = models.DecimalField(max_digits=18, decimal_places=4)
    amount = models.DecimalField(max_digits=24, decimal_places=2)
    display_name_snapshot = models.CharField(max_length=200)
    craft_name_snapshot = models.CharField(max_length=100)
    operation_name_snapshot = models.CharField(max_length=150)
    unit_name_snapshot = models.CharField(max_length=80)
    employee_name_snapshot = models.CharField(max_length=100)

    class Meta:
        db_table = "workshop_work_report_line"
        ordering = ["report", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["report", "line_number"], name="work_report_line_number_unique"),
            models.CheckConstraint(condition=Q(line_number__gt=0), name="work_report_line_positive"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="work_report_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price_snapshot__gte=0), name="work_report_price_nonnegative"),
            models.CheckConstraint(condition=Q(amount__gte=0), name="work_report_amount_nonnegative"),
            models.CheckConstraint(
                condition=Q(production_line__isnull=True) | Q(production_line__in=[1, 2, 3]),
                name="work_report_production_line_valid",
            ),
        ]


class WorkshopPlanExecution(TimeStampedModel):
    schedule_product = models.ForeignKey(
        "production_scheduling.ProductionScheduleProduct",
        on_delete=models.PROTECT,
        related_name="workshop_plan_executions",
    )
    craft = models.ForeignKey(
        "workshop_config.Craft", on_delete=models.PROTECT, related_name="plan_executions"
    )
    status = models.CharField(
        max_length=20, choices=WorkshopPlanStatus.choices, default=WorkshopPlanStatus.IN_PROGRESS
    )
    completed_at = models.DateTimeField(null=True, blank=True)
    completed_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="completed_workshop_plans",
    )

    class Meta:
        db_table = "workshop_plan_execution"
        ordering = ["schedule_product", "craft"]
        constraints = [
            models.UniqueConstraint(
                fields=["schedule_product", "craft"], name="workshop_plan_execution_unique"
            ),
            models.CheckConstraint(
                condition=Q(status__in=WorkshopPlanStatus.values),
                name="workshop_plan_execution_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["schedule_product", "status"], name="workshop_plan_exec_status_idx")
        ]
