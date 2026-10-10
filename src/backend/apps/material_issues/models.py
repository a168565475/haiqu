from decimal import Decimal

from django.core.exceptions import ValidationError
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import F, Q
from django.db.models.functions import Floor

from apps.core.models import TimeStampedModel


class MaterialIssueStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    PENDING_REVIEW = "PENDING_REVIEW", "待仓库审核"
    RETURNED = "RETURNED", "已退回"
    ISSUED = "ISSUED", "已出库"


class MaterialIssueLineType(models.TextChoices):
    RAW = "RAW", "原材料"
    SEMI = "SEMI", "委外回库半成品"


class MaterialIssueAction(models.TextChoices):
    CREATED = "CREATED", "创建"
    UPDATED = "UPDATED", "修改"
    SUBMITTED = "SUBMITTED", "提交审核"
    RETURNED = "RETURNED", "退回修改"
    ISSUED = "ISSUED", "确认出库"


class OrderMaterialRequirement(TimeStampedModel):
    measurement_kind = models.CharField(max_length=10, choices=[("OTHER", "原有单位"), ("PIPE", "管材支数")], default="OTHER")
    product_line = models.ForeignKey("production_tasks.ProductionTaskProduct", on_delete=models.PROTECT, null=True, blank=True, related_name="pipe_requirements")
    component_identity = models.UUIDField(null=True, blank=True)
    pieces_per_bar = models.PositiveBigIntegerField(null=True, blank=True)
    raw_bar_length_m = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    production_task = models.ForeignKey(
        "production_tasks.ProductionTask",
        on_delete=models.PROTECT,
        related_name="material_requirements",
    )
    raw_material = models.ForeignKey(
        "products.RawMaterialInformation",
        on_delete=models.PROTECT,
        related_name="order_requirements",
    )
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="order_material_requirements",
    )
    line_type = models.CharField(max_length=10, choices=MaterialIssueLineType.choices)
    section_code = models.CharField(max_length=30)
    required_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    internal_issued_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    outsourcing_issued_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    source_revision_hash = models.CharField(max_length=64)
    validation_errors = models.JSONField(default=list, blank=True)

    class Meta:
        db_table = "material_issue_order_requirement"
        ordering = ["production_task", "section_code", "raw_material", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["production_task", "raw_material", "unit", "line_type"],
                condition=Q(measurement_kind="OTHER"),
                name="mat_req_other_identity_uniq",
            ),
            models.UniqueConstraint(fields=["production_task", "product_line", "component_identity"], condition=Q(measurement_kind="PIPE"), name="mat_req_pipe_component_uniq"),
            models.CheckConstraint(
                condition=(Q(measurement_kind="OTHER", product_line__isnull=True, component_identity__isnull=True,
                             pieces_per_bar__isnull=True, raw_bar_length_m__isnull=True)
                    | Q(measurement_kind="PIPE", line_type="RAW", product_line__isnull=False,
                        component_identity__isnull=False, pieces_per_bar__isnull=False, pieces_per_bar__gt=0,
                        raw_bar_length_m__isnull=False, raw_bar_length_m__gt=0)),
                name="mat_req_pipe_shape_valid",
            ),
            models.CheckConstraint(
                condition=Q(measurement_kind="OTHER") | (
                    Q(required_quantity=Floor(F("required_quantity")), internal_issued_quantity=Floor(F("internal_issued_quantity")),
                      outsourcing_issued_quantity=Floor(F("outsourcing_issued_quantity")))
                    & Q(required_quantity__gte=F("internal_issued_quantity") + F("outsourcing_issued_quantity"))),
                name="mat_req_pipe_counts_valid",
            ),
            models.CheckConstraint(condition=Q(required_quantity__gt=0), name="mat_issue_req_qty_positive"),
            models.CheckConstraint(
                condition=Q(internal_issued_quantity__gte=0),
                name="mat_issue_req_internal_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(outsourcing_issued_quantity__gte=0),
                name="mat_issue_req_outsource_nonnegative",
            ),
            models.CheckConstraint(
                condition=Q(line_type__in=MaterialIssueLineType.values),
                name="mat_issue_req_type_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["production_task", "line_type", "section_code"], name="mat_issue_req_task_idx"),
            models.Index(fields=["raw_material", "unit"], name="mat_issue_req_material_idx"),
        ]


class RequirementContribution(TimeStampedModel):
    requirement = models.ForeignKey(
        OrderMaterialRequirement,
        on_delete=models.PROTECT,
        related_name="contributions",
    )
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct",
        on_delete=models.PROTECT,
        related_name="material_requirement_contributions",
    )
    bom = models.ForeignKey("boms.Bom", on_delete=models.PROTECT, related_name="material_requirement_contributions")
    bom_line = models.ForeignKey(
        "boms.BomLine",
        on_delete=models.PROTECT,
        related_name="material_requirement_contributions",
    )
    required_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    calculation_basis = models.JSONField(default=dict)
    source_revision_hash = models.CharField(max_length=64)
    is_current = models.BooleanField(default=True)

    class Meta:
        db_table = "material_issue_requirement_contribution"
        ordering = ["requirement", "product_line", "bom_line", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["requirement", "bom_line", "source_revision_hash"],
                name="mat_issue_contribution_revision_uniq",
            ),
            models.CheckConstraint(condition=Q(required_quantity__gt=0), name="mat_issue_contribution_qty_positive"),
        ]


class OrderSemiFinishedRequirement(TimeStampedModel):
    """接收订单自己的半成品额度，与公共实物余额分开记账。"""

    production_task = models.ForeignKey("production_tasks.ProductionTask", on_delete=models.PROTECT,
                                        related_name="semi_finished_requirements")
    product_line = models.ForeignKey("production_tasks.ProductionTaskProduct", on_delete=models.PROTECT,
                                     related_name="semi_finished_requirements")
    component_identity = models.UUIDField()
    bom_line = models.ForeignKey("boms.BomLine", on_delete=models.PROTECT, related_name="semi_finished_requirements")
    completed_craft = models.ForeignKey("workshop_config.Craft", on_delete=models.PROTECT,
                                        related_name="semi_finished_requirements")
    unit = models.ForeignKey("reference_data.ProductionUnit", on_delete=models.PROTECT,
                             related_name="semi_finished_requirements")
    identity_key = models.CharField(max_length=64)
    identity_snapshot = models.JSONField()
    source_snapshot = models.JSONField(default=dict)
    source_revision_hash = models.CharField(max_length=64)
    required_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))
    internal_issued_quantity = models.DecimalField(max_digits=18, decimal_places=4, default=Decimal("0"))

    class Meta:
        db_table = "order_semi_finished_requirement"
        ordering = ["production_task", "product_line", "component_identity", "completed_craft", "id"]
        constraints = [
            models.UniqueConstraint(fields=["production_task", "product_line", "component_identity", "completed_craft"],
                                    name="issue_semi_req_component_uniq"),
            models.CheckConstraint(condition=Q(required_quantity__gte=0, internal_issued_quantity__gte=0,
                                               required_quantity=Floor(F("required_quantity")),
                                               internal_issued_quantity=Floor(F("internal_issued_quantity"))),
                                   name="issue_semi_req_whole_qty"),
        ]
        indexes = [models.Index(fields=["production_task", "product_line"], name="issue_semi_req_order"),
                   models.Index(fields=["identity_key"], name="issue_semi_req_identity")]


class MaterialIssue(TimeStampedModel):
    stock_mode = models.CharField(max_length=16, choices=[("LEGACY", "原流程"), ("PUBLIC_V2", "公共库存")], default="LEGACY")
    issue_number = models.CharField(max_length=50, unique=True)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    production_task = models.ForeignKey(
        "production_tasks.ProductionTask",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_issues",
    )
    product_line = models.ForeignKey(
        "production_tasks.ProductionTaskProduct",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_issues",
    )
    workshop = models.ForeignKey(
        "workshop_config.Workshop",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_issues",
    )
    recipient_workshop_employee = models.ForeignKey(
        "workshop_config.WorkshopEmployee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_issues",
    )
    issue_at = models.DateTimeField(null=True, blank=True)
    remark = models.TextField(blank=True)
    status = models.CharField(max_length=30, choices=MaterialIssueStatus.choices, default=MaterialIssueStatus.DRAFT)
    version = models.PositiveIntegerField(default=1)
    source_revision_hash = models.CharField(max_length=64, blank=True)
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="created_material_issues",
    )
    updated_by_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="updated_material_issues",
    )
    submitted_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="submitted_material_issues",
    )
    submitted_at = models.DateTimeField(null=True, blank=True)
    issued_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issued_material_issues",
    )
    issued_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "material_issue"
        ordering = ["-created_at", "-id"]
        permissions = [
            ("view_all_materialissue", "可查看全部生产领料单"),
            ("submit_materialissue", "可提交生产领料申请"),
            ("review_materialissue", "可审核生产领料申请"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(status__in=MaterialIssueStatus.values), name="mat_issue_status_valid"),
            models.CheckConstraint(condition=Q(stock_mode__in=["LEGACY", "PUBLIC_V2"]), name="mat_issue_stock_mode_valid"),
            models.CheckConstraint(condition=Q(version__gt=0), name="mat_issue_version_positive"),
        ]
        indexes = [
            models.Index(fields=["status", "-created_at"], name="mat_issue_status_created_idx"),
            models.Index(fields=["production_task", "-created_at"], name="mat_issue_task_created_idx"),
            models.Index(fields=["workshop", "status"], name="mat_issue_workshop_idx"),
        ]

    def delete(self, *args, **kwargs):
        if self.status == MaterialIssueStatus.ISSUED:
            raise ValidationError("已出库领料单不允许删除。")
        return super().delete(*args, **kwargs)


class MaterialIssueLine(TimeStampedModel):
    semi_requirement = models.ForeignKey(OrderSemiFinishedRequirement, on_delete=models.PROTECT,
                                         null=True, blank=True, related_name="issue_lines")
    conversion_snapshot = models.JSONField(default=dict, blank=True)
    issue = models.ForeignKey(MaterialIssue, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    requirement = models.ForeignKey(
        OrderMaterialRequirement,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="issue_lines",
    )
    line_type = models.CharField(max_length=10, choices=MaterialIssueLineType.choices)
    raw_material = models.ForeignKey(
        "products.RawMaterialInformation",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_issue_lines",
    )
    semi_finished_balance = models.ForeignKey(
        "inventory.SemiFinishedStockBalance",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="material_issue_lines",
    )
    unit = models.ForeignKey(
        "reference_data.ProductionUnit",
        on_delete=models.PROTECT,
        related_name="material_issue_lines",
    )
    section_code_snapshot = models.CharField(max_length=30)
    material_number_snapshot = models.CharField(max_length=100)
    material_name_snapshot = models.CharField(max_length=200)
    specification_snapshot = models.CharField(max_length=300, blank=True)
    color_snapshot = models.CharField(max_length=200, blank=True)
    unit_snapshot = models.CharField(max_length=50)
    requested_quantity = models.DecimalField(
        max_digits=18,
        decimal_places=4,
        validators=[MinValueValidator(Decimal("0.0001"))],
    )
    issued_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)

    class Meta:
        db_table = "material_issue_line"
        ordering = ["issue", "line_number", "id"]
        constraints = [
            models.UniqueConstraint(fields=["issue", "line_number"], name="mat_issue_line_number_uniq"),
            models.UniqueConstraint(fields=["issue", "requirement"], name="mat_issue_line_requirement_uniq"),
            models.UniqueConstraint(fields=["issue", "semi_requirement"], name="mat_issue_public_semi_req_uniq"),
            models.UniqueConstraint(
                fields=["issue", "semi_finished_balance"],
                name="mat_issue_line_semi_balance_uniq",
            ),
            models.CheckConstraint(condition=Q(requested_quantity__gt=0), name="mat_issue_line_qty_positive"),
            models.CheckConstraint(
                condition=Q(issued_quantity__isnull=True) | Q(issued_quantity__gt=0),
                name="mat_issue_line_issued_positive",
            ),
            models.CheckConstraint(
                condition=Q(line_type__in=MaterialIssueLineType.values),
                name="mat_issue_line_type_valid",
            ),
            models.CheckConstraint(
                condition=(
                    Q(
                        line_type=MaterialIssueLineType.RAW,
                        requirement__isnull=False,
                        raw_material__isnull=False,
                        semi_finished_balance__isnull=True,
                        semi_requirement__isnull=True,
                    )
                    | Q(
                        line_type=MaterialIssueLineType.SEMI,
                        requirement__isnull=True,
                        raw_material__isnull=True,
                        semi_finished_balance__isnull=False,
                        semi_requirement__isnull=True,
                    )
                    | Q(line_type=MaterialIssueLineType.SEMI, requirement__isnull=True,
                        raw_material__isnull=True, semi_finished_balance__isnull=True,
                        semi_requirement__isnull=False)
                ),
                name="mat_issue_line_stock_identity_valid",
            ),
        ]


class MaterialIssuePublicStockAllocation(TimeStampedModel):
    """记录实际扣减的公共库区余额，不关联采购入库批次。"""

    line = models.ForeignKey(MaterialIssueLine, on_delete=models.PROTECT, related_name="public_stock_allocations")
    balance = models.ForeignKey("inventory.PublicStockBalance", on_delete=models.PROTECT,
                                related_name="material_issue_allocations")
    movement = models.OneToOneField("inventory.PublicStockMovement", on_delete=models.PROTECT,
                                    null=True, blank=True, related_name="material_issue_allocation")
    requested_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    stock_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    meter_quantity = models.DecimalField(max_digits=22, decimal_places=2, null=True, blank=True)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "material_issue_public_stock_allocation"
        ordering = ["line", "balance", "id"]
        constraints = [
            models.UniqueConstraint(fields=["line", "balance"], name="mat_issue_public_alloc_uniq"),
            models.CheckConstraint(condition=Q(requested_quantity__gt=0, stock_quantity__gt=0,
                                               requested_quantity=Floor(F("requested_quantity")),
                                               stock_quantity=Floor(F("stock_quantity")))
                                   & (Q(meter_quantity__isnull=True) | Q(meter_quantity__gt=0)),
                                   name="mat_issue_public_alloc_qty"),
        ]


class MaterialIssueBatchAllocation(TimeStampedModel):
    line = models.ForeignKey(MaterialIssueLine, on_delete=models.CASCADE, related_name="batch_allocations")
    inbound_line = models.ForeignKey("inventory.MaterialInboundLine", on_delete=models.PROTECT, related_name="issue_allocations")
    requested_pieces = models.PositiveBigIntegerField()
    bar_count = models.PositiveBigIntegerField()
    meters = models.DecimalField(max_digits=22, decimal_places=2)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "material_issue_batch_allocation"
        ordering = ["inbound_line_id", "id"]
        constraints = [
            models.UniqueConstraint(fields=["line", "inbound_line"], name="mat_issue_batch_unique"),
            models.CheckConstraint(condition=Q(requested_pieces__gt=0, bar_count__gt=0, meters__gt=0), name="mat_issue_batch_positive"),
        ]


class MaterialIssueAuditEvent(TimeStampedModel):
    issue = models.ForeignKey(MaterialIssue, on_delete=models.PROTECT, related_name="audit_events")
    action = models.CharField(max_length=20, choices=MaterialIssueAction.choices)
    issue_version = models.PositiveIntegerField()
    actor_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="material_issue_audit_events",
    )
    reason = models.TextField(blank=True)
    request_id = models.UUIDField(null=True, blank=True, unique=True)
    request_payload_hash = models.CharField(max_length=64, blank=True)
    snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "material_issue_audit_event"
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(action__in=MaterialIssueAction.values), name="mat_issue_event_action_valid"),
            models.CheckConstraint(condition=Q(issue_version__gt=0), name="mat_issue_event_version_positive"),
        ]
        indexes = [models.Index(fields=["issue", "created_at"], name="mat_issue_event_issue_idx")]


class MetalProcessingSource(TimeStampedModel):
    """已出库领料的加工额度；不代表仓库库存。"""

    issue_line = models.OneToOneField(MaterialIssueLine, on_delete=models.PROTECT, related_name="processing_source")
    source_snapshot = models.JSONField()
    source_hash = models.CharField(max_length=64)
    issued_pieces = models.PositiveBigIntegerField()
    completed_pieces = models.PositiveBigIntegerField(default=0)
    reserved_pieces = models.PositiveBigIntegerField(default=0)
    internal_received_pieces = models.PositiveBigIntegerField(default=0)
    dispatched_pieces = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=10, choices=[("OPEN", "未结清"), ("CLOSED", "已结清")], default="OPEN")
    version = models.PositiveIntegerField(default=1)

    class Meta:
        db_table = "metal_processing_source"
        default_permissions = ("view",)
        permissions = [
            ("register_metalprocessingcompletion", "可登记金工合格完成支数"),
            ("close_metalprocessingsource", "可备注结清金工加工来源"),
            ("create_metalprocessingoriginalhandoff", "可登记金工完成件原外发交接"),
            ("register_metalprocessingunsprayedreturn", "可登记未喷塑管件退回"),
            ("register_metalprocessingrework", "可登记退回管件重新加工"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(issued_pieces__gt=0), name="metal_source_issued_positive"),
            models.CheckConstraint(condition=Q(completed_pieces__lte=F("issued_pieces")), name="metal_source_completed_limit"),
            models.CheckConstraint(
                condition=Q(completed_pieces__gte=F("reserved_pieces") + F("dispatched_pieces") + F("internal_received_pieces")),
                name="metal_source_handoff_limit",
            ),
            models.CheckConstraint(condition=Q(status__in=["OPEN", "CLOSED"]), name="metal_source_status_valid"),
            models.CheckConstraint(condition=Q(version__gt=0), name="metal_source_version_positive"),
        ]


class MetalProcessingCompletion(TimeStampedModel):
    source = models.ForeignKey(MetalProcessingSource, on_delete=models.PROTECT, related_name="completions")
    good_pieces = models.PositiveBigIntegerField()
    completion_date = models.DateField()
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    source_version = models.PositiveIntegerField()
    result_snapshot = models.JSONField()

    class Meta:
        db_table = "metal_processing_completion"
        default_permissions = ()
        ordering = ["created_at", "id"]
        constraints = [
            models.CheckConstraint(condition=Q(good_pieces__gt=0), name="metal_completion_positive"),
            models.CheckConstraint(condition=Q(source_version__gt=0), name="metal_completion_version_positive"),
        ]


class MetalProcessingClosure(TimeStampedModel):
    source = models.OneToOneField(MetalProcessingSource, on_delete=models.PROTECT, related_name="closure")
    remark = models.CharField(max_length=1000)
    quantity_snapshot = models.JSONField()
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    source_version = models.PositiveIntegerField()
    result_snapshot = models.JSONField()

    class Meta:
        db_table = "metal_processing_closure"
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=~Q(remark=""), name="metal_closure_remark_required"),
            models.CheckConstraint(condition=Q(source_version__gt=0), name="metal_closure_version_positive"),
        ]


class MetalProcessingOriginalHandoff(TimeStampedModel):
    """P4 原金工完成件交给喷塑厂的实际交接快照。只增加已交接，不恢复原料。"""

    source = models.ForeignKey(MetalProcessingSource, on_delete=models.PROTECT, related_name="original_handoffs")
    original_order = models.ForeignKey("outsourcing.OutsourcingOrder", on_delete=models.PROTECT, related_name="metal_processing_original_handoffs")
    factory = models.ForeignKey("outsourcing.OutsourcingFactory", on_delete=models.PROTECT, related_name="metal_processing_original_handoffs")
    handoff_pieces = models.PositiveBigIntegerField()
    handoff_date = models.DateField()
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="metal_processing_original_handoffs")
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "metal_processing_original_handoff"
        ordering = ["-created_at", "-id"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(handoff_pieces__gt=0), name="metal_orig_handoff_positive"),
        ]


class OriginalHandoffPublicTransition(TimeStampedModel):
    """旧直接交接的不可变接续凭证；本记录不产生库存或增加订单额度。"""

    original_handoff = models.OneToOneField(MetalProcessingOriginalHandoff, on_delete=models.PROTECT, related_name="public_transition")
    source_hash = models.CharField(max_length=64)
    handoff_snapshot_hash = models.CharField(max_length=64)
    manifest_hash = models.CharField(max_length=64)
    public_identity = models.JSONField()
    evidence = models.JSONField()
    quantity_snapshot = models.JSONField()
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="+")
    request_id = models.UUIDField(db_index=True)
    request_payload_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "metal_original_handoff_public_transition"
        default_permissions = ("view",)
        permissions = [("apply_originalhandoffpublictransition", "可在维护期接续旧金工直接交接")]

    def save(self, *args, **kwargs):
        if not self._state.adding:
            raise ValidationError("旧单接续凭证只允许新增，不允许修改。")
        return super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("旧单接续凭证不允许删除。")


class MetalProcessingUnsprayedReturn(TimeStampedModel):
    """未喷塑退回金工暂存记录，不产生原料或可领库存。"""

    original_handoff = models.ForeignKey(MetalProcessingOriginalHandoff, on_delete=models.PROTECT, related_name="unsprayed_returns")
    returned_pieces = models.PositiveBigIntegerField()
    received_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="metal_processing_unsprayed_returns")
    storage_location = models.CharField(max_length=200)
    remark = models.CharField(max_length=1000, blank=True)
    return_date = models.DateField()
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "metal_processing_unsprayed_return"
        ordering = ["-created_at", "-id"]
        default_permissions = ()
        constraints = [
            models.CheckConstraint(condition=Q(returned_pieces__gt=0), name="metal_unsprayed_return_positive"),
            models.CheckConstraint(condition=~Q(storage_location=""), name="metal_unsprayed_location_required"),
        ]


class MetalProcessingRework(TimeStampedModel):
    """退回暂存件再次加工形成的新完成量。"""

    unsprayed_return = models.ForeignKey(MetalProcessingUnsprayedReturn, on_delete=models.PROTECT, related_name="reworks")
    source = models.ForeignKey(MetalProcessingSource, on_delete=models.PROTECT, related_name="reworks")
    completed_pieces = models.PositiveBigIntegerField()
    completion_date = models.DateField()
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="metal_processing_reworks")
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "metal_processing_rework"
        ordering = ["-created_at", "-id"]
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(completed_pieces__gt=0), name="metal_rework_positive")]


class MetalProcessingExternalOrderStatus(models.TextChoices):
    PENDING_HANDOFF = "PENDING_HANDOFF", "待交接"
    PROCESSING = "PROCESSING", "加工中"
    CLOSED = "CLOSED", "已结清"
    COMPLETED = "COMPLETED", "已完成"


class MetalProcessingExternalOrder(TimeStampedModel):
    """P4 重新加工后的独立喷塑外发单，和原外发单完全分开。"""

    stock_mode = models.CharField(max_length=16, choices=[("LEGACY", "原流程"), ("PUBLIC_V2", "公共库存")], default="LEGACY")
    output_identity_snapshot = models.JSONField(default=dict, blank=True)
    order_number = models.CharField(max_length=50, unique=True)
    rework = models.ForeignKey(MetalProcessingRework, on_delete=models.PROTECT, related_name="external_orders")
    source = models.ForeignKey(MetalProcessingSource, on_delete=models.PROTECT, related_name="p4_external_orders")
    original_return = models.ForeignKey(MetalProcessingUnsprayedReturn, on_delete=models.PROTECT, related_name="external_orders")
    factory = models.ForeignKey("outsourcing.OutsourcingFactory", on_delete=models.PROTECT, related_name="metal_processing_external_orders")
    craft = models.ForeignKey("workshop_config.Craft", on_delete=models.PROTECT, related_name="metal_processing_external_orders")
    allocated_pieces = models.PositiveBigIntegerField()
    handoff_pieces = models.PositiveBigIntegerField(default=0)
    returned_good_pieces = models.PositiveBigIntegerField(default=0)
    status = models.CharField(max_length=20, choices=MetalProcessingExternalOrderStatus.choices, default=MetalProcessingExternalOrderStatus.PENDING_HANDOFF)
    version = models.PositiveIntegerField(default=1)
    client_request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    created_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="created_metal_processing_external_orders")
    updated_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="updated_metal_processing_external_orders")
    completed_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "metal_processing_external_order"
        ordering = ["-created_at", "-id"]
        default_permissions = ("add", "change", "delete", "view")
        permissions = [
            ("create_metalprocessingexternalorder", "可创建管材重新加工外发单"),
            ("confirm_metalprocessingexternalhandoff", "可确认管材重新加工外发交接"),
            ("confirm_metalprocessingexternalreturn", "可确认管材重新加工合格回货"),
            ("close_metalprocessingexternalorder", "可备注结清管材重新加工外发单"),
        ]
        constraints = [
            models.CheckConstraint(condition=Q(allocated_pieces__gt=0), name="metal_p4_order_allocated_positive"),
            models.CheckConstraint(condition=Q(handoff_pieces__gte=0) & Q(handoff_pieces__lte=F("allocated_pieces")), name="metal_p4_order_handoff_limit"),
            models.CheckConstraint(condition=Q(returned_good_pieces__gte=0) & Q(returned_good_pieces__lte=F("handoff_pieces")), name="metal_p4_order_return_limit"),
            models.CheckConstraint(condition=Q(version__gt=0), name="metal_p4_order_version_positive"),
            models.CheckConstraint(condition=Q(status__in=MetalProcessingExternalOrderStatus.values), name="metal_p4_order_status_valid"),
            models.CheckConstraint(condition=Q(stock_mode__in=["LEGACY", "PUBLIC_V2"]), name="metal_p4_order_stock_mode"),
        ]


class MetalProcessingExternalHandoff(TimeStampedModel):
    order = models.OneToOneField(MetalProcessingExternalOrder, on_delete=models.PROTECT, related_name="handoff")
    handoff_pieces = models.PositiveBigIntegerField()
    handoff_date = models.DateField()
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="metal_processing_external_handoffs")
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)

    class Meta:
        db_table = "metal_processing_external_handoff"
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(handoff_pieces__gt=0), name="metal_p4_handoff_positive")]


class MetalProcessingExternalGoodReturn(TimeStampedModel):
    order = models.ForeignKey(MetalProcessingExternalOrder, on_delete=models.PROTECT, related_name="good_returns")
    return_number = models.CharField(max_length=50, unique=True)
    good_pieces = models.PositiveBigIntegerField()
    zone = models.ForeignKey("inventory.WarehouseZone", on_delete=models.PROTECT, related_name="metal_processing_external_good_returns")
    received_by_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="received_metal_processing_external_good_returns")
    return_date = models.DateField()
    remark = models.CharField(max_length=1000, blank=True)
    post_closure = models.BooleanField(default=False)
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)
    snapshot = models.JSONField(default=dict)
    public_stock_movement = models.OneToOneField(
        "inventory.PublicStockMovement", null=True, blank=True, on_delete=models.PROTECT,
        related_name="metal_processing_good_return",
    )

    class Meta:
        db_table = "metal_processing_external_good_return"
        ordering = ["-created_at", "-id"]
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=Q(good_pieces__gt=0), name="metal_p4_good_return_positive")]


class MetalProcessingExternalClosure(TimeStampedModel):
    order = models.OneToOneField(MetalProcessingExternalOrder, on_delete=models.PROTECT, related_name="closure")
    remark = models.CharField(max_length=1000)
    quantity_snapshot = models.JSONField()
    actor_employee = models.ForeignKey("organizations.Employee", on_delete=models.PROTECT, related_name="closed_metal_processing_external_orders")
    request_id = models.UUIDField(unique=True)
    request_payload_hash = models.CharField(max_length=64)

    class Meta:
        db_table = "metal_processing_external_closure"
        default_permissions = ()
        constraints = [models.CheckConstraint(condition=~Q(remark=""), name="metal_p4_closure_remark_required")]
