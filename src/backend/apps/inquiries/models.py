from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Q

from apps.core.models import (
    ArchivableModel,
    TimeStampedModel,
    currency_code_validator,
    uppercase_code_condition,
    uppercase_code_validator,
)


def format_inquiry_item_specification(specification="", color="", material=""):
    """把询盘的分栏属性组合成旧报价/样品快照仍能承载的文本。"""
    parts = [str(specification or "").strip()]
    if str(color or "").strip():
        parts.append(f"颜色：{str(color).strip()}")
    if str(material or "").strip():
        parts.append(f"材质：{str(material).strip()}")
    return "；".join(part for part in parts if part)


class InquiryStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    NEW = "NEW", "待确认"
    ANALYZING = "ANALYZING", "需求分析中"
    READY_FOR_QUOTE = "READY_FOR_QUOTE", "待报价"
    QUOTING = "QUOTING", "报价中"
    QUOTED = "QUOTED", "已报价"
    FOLLOW_UP = "FOLLOW_UP", "客户跟进中"
    QUOTE_ACCEPTED = "QUOTE_ACCEPTED", "报价已接受"
    CONVERTED = "CONVERTED", "已创建销售订单"
    LOST = "LOST", "已丢失"
    CLOSED = "CLOSED", "已关闭"
    CANCELLED = "CANCELLED", "已取消"


class InquiryPriority(models.TextChoices):
    HIGH = "HIGH", "高"
    MEDIUM = "MEDIUM", "中"
    LOW = "LOW", "低"


class InquiryItemMatchStatus(models.TextChoices):
    PENDING = "PENDING", "待匹配"
    MATCHED = "MATCHED", "已匹配"
    NOT_REQUIRED = "NOT_REQUIRED", "无需匹配"


class Inquiry(ArchivableModel):
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        related_name="inquiries",
    )
    transaction_entity = models.ForeignKey(
        "customers.CustomerTransactionEntity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="inquiries",
    )
    customer_contact = models.ForeignKey(
        "customers.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="inquiries",
    )
    owner_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="owned_inquiries",
    )
    inquiry_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    status = models.CharField(max_length=20, choices=InquiryStatus.choices, default=InquiryStatus.DRAFT)
    priority = models.CharField(max_length=10, choices=InquiryPriority.choices, blank=True, default="")
    inquiry_source = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    subject = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    received_at = models.DateTimeField()
    requested_due_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    source_system = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    external_id = models.CharField(max_length=150, blank=True)
    customer_snapshot = models.JSONField(default=dict, blank=True)
    source_snapshot = models.JSONField(default=dict, blank=True)
    snapshot_schema_version = models.PositiveSmallIntegerField(default=1)
    assigned_at = models.DateTimeField(null=True, blank=True)
    close_reason_code = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    close_reason_detail = models.TextField(blank=True)
    customer_language_code = models.CharField(max_length=30, blank=True, validators=[uppercase_code_validator])
    trade_term_code = models.CharField(max_length=30, blank=True, validators=[uppercase_code_validator])
    trade_term_place = models.CharField(max_length=150, blank=True)
    delivery_requirement = models.CharField(max_length=250, blank=True)
    estimated_amount_min = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    estimated_amount_max = models.DecimalField(max_digits=18, decimal_places=2, null=True, blank=True)
    estimated_currency_code = models.CharField(max_length=3, blank=True, validators=[currency_code_validator])
    draft_version = models.PositiveIntegerField(default=0)
    creation_idempotency_key = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "inquiry"
        constraints = [
            models.CheckConstraint(condition=Q(priority__in=["", *InquiryPriority.values]), name="inquiry_priority_valid"),
            models.CheckConstraint(condition=Q(status__in=InquiryStatus.values), name="inquiry_status_valid"),
            models.CheckConstraint(
                condition=uppercase_code_condition("inquiry_number"),
                name="inquiry_number_uppercase",
            ),
            models.CheckConstraint(
                condition=Q(source_system="", external_id="")
                | (~Q(source_system="") & ~Q(external_id="")),
                name="inquiry_source_pair_consistent",
            ),
            models.UniqueConstraint(
                fields=["source_system", "external_id"],
                condition=~Q(source_system="") & ~Q(external_id=""),
                name="inquiry_external_source_uniq",
            ),
            models.UniqueConstraint(
                fields=["creation_idempotency_key"],
                condition=~Q(creation_idempotency_key=""),
                name="inquiry_create_idempotency_uniq",
            ),
            models.CheckConstraint(
                condition=(
                    Q(estimated_amount_min__isnull=True, estimated_amount_max__isnull=True, estimated_currency_code="")
                    | (
                        Q(estimated_amount_min__gte=0)
                        & Q(estimated_amount_max__gte=F("estimated_amount_min"))
                        & ~Q(estimated_currency_code="")
                    )
                ),
                name="inquiry_estimated_amount_valid",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner_employee", "status", "-received_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="inquiry_owner_status_idx",
            ),
            models.Index(
                fields=["status", "assigned_at", "-received_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="inquiry_assignment_queue_idx",
            ),
            models.Index(
                fields=["status", "-received_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="inquiry_status_list_idx",
            ),
            models.Index(
                fields=["customer_account", "-received_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="inquiry_customer_idx",
            ),
            models.Index(
                fields=["transaction_entity", "-received_at", "-id"],
                condition=Q(transaction_entity__isnull=False, archived_at__isnull=True),
                name="inquiry_entity_idx",
            ),
            models.Index(
                fields=["customer_contact", "-received_at", "-id"],
                condition=Q(customer_contact__isnull=False, archived_at__isnull=True),
                name="inquiry_contact_idx",
            ),
        ]
        permissions = [
            ("assign_inquiry", "可分配询盘"),
            ("bulk_change_inquiry", "可批量变更询盘"),
        ]

    def __str__(self):
        return f"{self.inquiry_number} - {self.subject}"

    def clean(self):
        super().clean()
        errors = {}
        if self.transaction_entity_id and self.transaction_entity.customer_account_id != self.customer_account_id:
            errors["transaction_entity"] = "询价交易主体必须属于同一客户账户。"
        if self.customer_contact_id and self.customer_contact.customer_account_id != self.customer_account_id:
            errors["customer_contact"] = "询价联系人必须属于同一客户账户。"
        if errors:
            raise ValidationError(errors)


class InquiryItem(TimeStampedModel):
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="items")
    line_number = models.PositiveIntegerField()
    product_description = models.CharField(max_length=500)
    specification = models.TextField(blank=True)
    color = models.TextField(blank=True, default="")
    material = models.TextField(blank=True, default="")
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    target_unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_currency_code = models.CharField(max_length=3, blank=True, validators=[currency_code_validator])
    expected_date = models.DateField(null=True, blank=True)
    product_match_status = models.CharField(
        max_length=30,
        choices=InquiryItemMatchStatus.choices,
        default=InquiryItemMatchStatus.PENDING,
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "inquiry_item"
        ordering = ["inquiry", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["inquiry", "line_number"], name="inquiry_item_line_uniq"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="inquiry_item_qty_positive"),
            models.CheckConstraint(
                condition=Q(target_unit_price__isnull=True) | Q(target_unit_price__gte=0),
                name="inquiry_item_target_price_nonneg",
            ),
        ]


class InquiryDraftRevision(TimeStampedModel):
    """整单草稿保存的版本与幂等记录，仅保留询盘自身事实快照。"""

    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="draft_revisions")
    revision_number = models.PositiveIntegerField()
    idempotency_key = models.CharField(max_length=64, blank=True)
    snapshot = models.JSONField(default=dict)
    saved_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="saved_inquiry_draft_revisions",
    )

    class Meta:
        db_table = "inquiry_draft_revision"
        ordering = ["-revision_number", "-id"]
        constraints = [
            models.UniqueConstraint(fields=["inquiry", "revision_number"], name="inquiry_draft_revision_number_uniq"),
            models.UniqueConstraint(
                fields=["inquiry", "idempotency_key"],
                condition=~Q(idempotency_key=""),
                name="inquiry_draft_revision_idempotency_uniq",
            ),
        ]
        indexes = [models.Index(fields=["inquiry", "-revision_number"], name="inquiry_draft_revision_idx")]


class InquiryTaskLink(TimeStampedModel):
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="task_links")
    business_task = models.ForeignKey("workflow.BusinessTask", on_delete=models.PROTECT, related_name="inquiry_links")
    is_primary_source = models.BooleanField(default=True)

    class Meta:
        db_table = "inquiry_task_link"
        constraints = [
            models.UniqueConstraint(fields=["inquiry", "business_task"], name="inquiry_task_link_uniq"),
            models.UniqueConstraint(
                fields=["business_task"],
                condition=Q(is_primary_source=True),
                name="inquiry_task_primary_uniq",
            ),
        ]


class InquirySlaLink(TimeStampedModel):
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="sla_links")
    sla_tracking = models.OneToOneField(
        "workflow.SlaTracking",
        on_delete=models.PROTECT,
        related_name="inquiry_link",
    )
    stage_code = models.CharField(max_length=50, default="FIRST_RESPONSE", validators=[uppercase_code_validator])
    is_current = models.BooleanField(default=True)

    class Meta:
        db_table = "inquiry_sla_link"
        constraints = [
            models.UniqueConstraint(
                fields=["inquiry", "stage_code"],
                condition=Q(is_current=True),
                name="inquiry_sla_current_stage_uniq",
            ),
        ]


class InquiryAssignmentHistory(TimeStampedModel):
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="assignment_history")
    previous_owner_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="inquiry_assignments_from",
    )
    new_owner_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.PROTECT,
        related_name="inquiry_assignments_to",
    )
    assigned_by_employee = models.ForeignKey(
        "organizations.Employee", null=True, blank=True, on_delete=models.SET_NULL,
        related_name="inquiry_assignments_performed",
    )
    assignment_reason = models.CharField(max_length=500, blank=True)
    assignment_type = models.CharField(max_length=30, default="MANUAL", validators=[uppercase_code_validator])
    assigned_at = models.DateTimeField()

    class Meta:
        db_table = "inquiry_assignment_history"
        ordering = ["-assigned_at", "-id"]
        indexes = [
            models.Index(fields=["inquiry", "-assigned_at", "-id"], name="inquiry_assign_history_idx"),
        ]


class InquiryFileLink(TimeStampedModel):
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="file_links")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="inquiry_links")
    file_role = models.CharField(max_length=50, validators=[uppercase_code_validator])

    class Meta:
        db_table = "inquiry_file_link"
        constraints = [
            models.UniqueConstraint(fields=["inquiry", "business_file"], name="inquiry_file_link_uniq"),
        ]
