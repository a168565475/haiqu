from django.contrib.postgres.constraints import ExclusionConstraint
from django.contrib.postgres.fields import DecimalRangeField, RangeBoundary, RangeOperators
from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import F, Func, Q

from apps.core.models import (
    ArchivableModel,
    TimeStampedModel,
    currency_code_validator,
    uppercase_code_condition,
    uppercase_code_validator,
)


class NumericRange(Func):
    function = "NUMRANGE"
    output_field = DecimalRangeField()


class QuotationOutcomeStatus(models.TextChoices):
    OPEN = "OPEN", "进行中"
    WON = "WON", "已接受"
    LOST = "LOST", "已失单"
    CANCELLED = "CANCELLED", "已取消"


class QuotationTemplate(ArchivableModel):
    template_code = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    template_name = models.CharField(max_length=200)
    template_version = models.PositiveIntegerField(default=1)
    requires_approval = models.BooleanField(default=False)
    template_config = models.JSONField(default=dict)

    class Meta:
        db_table = "quotation_template"
        ordering = ["template_code"]
        constraints = [
            models.CheckConstraint(
                condition=uppercase_code_condition("template_code"),
                name="quote_template_code_uppercase",
            ),
        ]

    def __str__(self):
        return f"{self.template_code} - {self.template_name}"


class Quotation(ArchivableModel):
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        related_name="quotations",
    )
    transaction_entity = models.ForeignKey(
        "customers.CustomerTransactionEntity",
        on_delete=models.PROTECT,
        related_name="quotations",
    )
    source_inquiry = models.ForeignKey(
        "inquiries.Inquiry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotations",
    )
    owner_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="owned_quotations",
    )
    quotation_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    outcome_status = models.CharField(
        max_length=20,
        choices=QuotationOutcomeStatus.choices,
        default=QuotationOutcomeStatus.OPEN,
    )
    accepted_version = models.ForeignKey(
        "QuotationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="accepted_by_quotations",
    )
    subject = models.CharField(max_length=250)
    outcome_note = models.TextField(blank=True)

    class Meta:
        db_table = "quotation"
        permissions = [
            ("issue_quotation", "可签发报价"),
            ("dispatch_quotation", "可发送报价"),
            ("accept_quotation", "可确认报价被接受"),
            ("approve_quotation", "可审批报价"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(outcome_status__in=QuotationOutcomeStatus.values),
                name="quotation_outcome_status_valid",
            ),
            models.CheckConstraint(
                condition=uppercase_code_condition("quotation_number"),
                name="quotation_number_uppercase",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner_employee", "outcome_status", "-updated_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="quotation_owner_outcome_idx",
            ),
            models.Index(
                fields=["customer_account", "-created_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="quotation_customer_idx",
            ),
            models.Index(
                fields=["source_inquiry", "-created_at", "-id"],
                condition=Q(source_inquiry__isnull=False, archived_at__isnull=True),
                name="quotation_inquiry_idx",
            ),
            models.Index(
                fields=["transaction_entity", "-created_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="quotation_entity_idx",
            ),
        ]

    def __str__(self):
        return f"{self.quotation_number} - {self.subject}"

    def clean(self):
        super().clean()
        errors = {}
        if self.transaction_entity_id and self.transaction_entity.customer_account_id != self.customer_account_id:
            errors["transaction_entity"] = "报价交易主体必须属于同一客户账户。"
        if self.source_inquiry_id and self.source_inquiry.customer_account_id != self.customer_account_id:
            errors["source_inquiry"] = "来源询价必须属于同一客户账户。"
        if self.accepted_version_id and self.accepted_version.quotation_id != self.id:
            errors["accepted_version"] = "接受版本必须属于当前报价。"
        if errors:
            raise ValidationError(errors)


class QuotationVersionStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    LOCKED = "LOCKED", "已锁定"
    ISSUED = "ISSUED", "已签发"
    SENT = "SENT", "已发送"
    SUPERSEDED = "SUPERSEDED", "已被新版本替代"
    VOID = "VOID", "已作废"


class QuotationVersion(TimeStampedModel):
    quotation = models.ForeignKey(Quotation, on_delete=models.PROTECT, related_name="versions")
    quotation_template = models.ForeignKey(
        QuotationTemplate,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_versions",
    )
    version_number = models.PositiveIntegerField()
    status = models.CharField(
        max_length=20,
        choices=QuotationVersionStatus.choices,
        default=QuotationVersionStatus.DRAFT,
    )
    currency_code = models.CharField(max_length=3, validators=[currency_code_validator])
    language_code = models.CharField(max_length=20, default="zh-hans")
    subtotal_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    discount_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    tax_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    total_amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    issued_at = models.DateTimeField(null=True, blank=True)
    valid_until = models.DateField(null=True, blank=True)
    locked_at = models.DateTimeField(null=True, blank=True)
    locked_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="locked_quotation_versions",
    )
    transaction_entity_snapshot = models.JSONField(default=dict, blank=True)
    address_snapshot = models.JSONField(default=dict, blank=True)
    contact_snapshot = models.JSONField(default=dict, blank=True)
    template_snapshot = models.JSONField(default=dict, blank=True)
    terms_snapshot = models.JSONField(default=dict, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "quotation_version"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=QuotationVersionStatus.values),
                name="quotation_version_status_valid",
            ),
            models.UniqueConstraint(fields=["quotation", "version_number"], name="quotation_version_number_uniq"),
            models.CheckConstraint(
                condition=Q(subtotal_amount__gte=0)
                & Q(discount_amount__gte=0)
                & Q(tax_amount__gte=0)
                & Q(total_amount__gte=0),
                name="quotation_version_amounts_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(status=QuotationVersionStatus.DRAFT, locked_at__isnull=True)
                | (~Q(status=QuotationVersionStatus.DRAFT) & Q(locked_at__isnull=False)),
                name="quotation_lock_state_consistent",
            ),
        ]
        indexes = [
            models.Index(
                fields=["status", "-issued_at", "-id"],
                condition=Q(status__in=[QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT]),
                name="quote_version_issued_idx",
            ),
            models.Index(
                fields=["valid_until", "id"],
                condition=Q(
                    valid_until__isnull=False,
                    status__in=[QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT],
                ),
                name="quote_version_expiry_idx",
            ),
        ]

    def clean(self):
        super().clean()
        if self.status in {QuotationVersionStatus.ISSUED, QuotationVersionStatus.SENT}:
            missing = []
            if not self.transaction_entity_snapshot:
                missing.append("transaction_entity_snapshot")
            if not self.address_snapshot:
                missing.append("address_snapshot")
            if not self.contact_snapshot:
                missing.append("contact_snapshot")
            if missing:
                raise ValidationError({field: "正式报价必须保存完整快照。" for field in missing})


class QuotationLine(TimeStampedModel):
    quotation_version = models.ForeignKey(QuotationVersion, on_delete=models.PROTECT, related_name="lines")
    line_number = models.PositiveIntegerField()
    product_description_snapshot = models.CharField(max_length=500)
    specification_snapshot = models.TextField(blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)
    discount_rate = models.DecimalField(max_digits=7, decimal_places=6, default=0)
    line_total = models.DecimalField(max_digits=18, decimal_places=4)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "quotation_line"
        ordering = ["quotation_version", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["quotation_version", "line_number"], name="quotation_line_number_uniq"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="quotation_line_qty_positive"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="quotation_line_price_nonneg"),
            models.CheckConstraint(
                condition=Q(discount_rate__gte=0) & Q(discount_rate__lte=1),
                name="quotation_line_discount_range",
            ),
            models.CheckConstraint(condition=Q(line_total__gte=0), name="quotation_line_total_nonneg"),
        ]


class QuotationQuantityTier(TimeStampedModel):
    quotation_line = models.ForeignKey(QuotationLine, on_delete=models.PROTECT, related_name="quantity_tiers")
    min_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    max_quantity = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "quotation_quantity_tier"
        constraints = [
            models.CheckConstraint(condition=Q(min_quantity__gt=0), name="quote_tier_min_qty_positive"),
            models.CheckConstraint(
                condition=Q(max_quantity__isnull=True) | Q(max_quantity__gt=F("min_quantity")),
                name="quote_tier_valid_range",
            ),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="quote_tier_price_nonneg"),
            ExclusionConstraint(
                name="quote_tier_no_overlap",
                expressions=[
                    ("quotation_line", RangeOperators.EQUAL),
                    (NumericRange("min_quantity", "max_quantity", RangeBoundary()), RangeOperators.OVERLAPS),
                ],
            ),
        ]


class QuotationDocumentType(models.TextChoices):
    DRAFT = "DRAFT", "草稿文档"
    FORMAL = "FORMAL", "正式报价"
    OTHER = "OTHER", "其他"


class QuotationDocument(TimeStampedModel):
    quotation_version = models.ForeignKey(QuotationVersion, on_delete=models.PROTECT, related_name="documents")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="quotation_documents")
    document_type = models.CharField(max_length=20, choices=QuotationDocumentType.choices)
    is_formal = models.BooleanField(default=False)
    generated_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="generated_quotation_documents",
    )
    generated_at = models.DateTimeField()
    snapshot_hash = models.CharField(max_length=128)

    class Meta:
        db_table = "quotation_document"
        constraints = [
            models.UniqueConstraint(
                fields=["quotation_version"],
                condition=Q(is_formal=True),
                name="quotation_one_formal_doc_uniq",
            ),
        ]


class FollowUpStatus(models.TextChoices):
    PENDING = "PENDING", "待跟进"
    COMPLETED = "COMPLETED", "已完成"
    CANCELLED = "CANCELLED", "已取消"


class QuotationDispatchRecord(TimeStampedModel):
    quotation_version = models.ForeignKey(QuotationVersion, on_delete=models.PROTECT, related_name="dispatch_records")
    dispatched_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotation_dispatches",
    )
    channel = models.CharField(max_length=50, validators=[uppercase_code_validator])
    recipient_snapshot = models.JSONField(default=dict)
    dispatched_at = models.DateTimeField()
    external_reference = models.CharField(max_length=250, blank=True)
    follow_up_due_at = models.DateTimeField(null=True, blank=True)
    follow_up_status = models.CharField(
        max_length=20,
        choices=FollowUpStatus.choices,
        default=FollowUpStatus.PENDING,
    )
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "quotation_dispatch_record"
        constraints = [
            models.CheckConstraint(
                condition=Q(follow_up_status__in=FollowUpStatus.values),
                name="quote_followup_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["quotation_version", "-dispatched_at", "-id"], name="quote_dispatch_history_idx"),
            models.Index(
                fields=["follow_up_due_at", "id"],
                condition=Q(follow_up_status=FollowUpStatus.PENDING, follow_up_due_at__isnull=False),
                name="quote_dispatch_followup_idx",
            ),
        ]


class QuotationVersionTaskLink(TimeStampedModel):
    quotation_version = models.ForeignKey(QuotationVersion, on_delete=models.PROTECT, related_name="task_links")
    business_task = models.ForeignKey("workflow.BusinessTask", on_delete=models.PROTECT, related_name="quotation_links")
    is_primary_source = models.BooleanField(default=True)

    class Meta:
        db_table = "quotation_version_task_link"
        constraints = [
            models.UniqueConstraint(
                fields=["quotation_version", "business_task"],
                name="quotation_task_link_uniq",
            ),
            models.UniqueConstraint(
                fields=["business_task"],
                condition=Q(is_primary_source=True),
                name="quotation_task_primary_uniq",
            ),
        ]


class QuotationVersionSlaLink(TimeStampedModel):
    quotation_version = models.ForeignKey(QuotationVersion, on_delete=models.PROTECT, related_name="sla_links")
    sla_tracking = models.OneToOneField(
        "workflow.SlaTracking",
        on_delete=models.PROTECT,
        related_name="quotation_link",
    )

    class Meta:
        db_table = "quotation_version_sla_link"


class QuotationVersionApprovalLink(TimeStampedModel):
    quotation_version = models.ForeignKey(QuotationVersion, on_delete=models.PROTECT, related_name="approval_links")
    approval_request = models.OneToOneField(
        "workflow.ApprovalRequest",
        on_delete=models.PROTECT,
        related_name="quotation_link",
    )

    class Meta:
        db_table = "quotation_version_approval_link"


class QuotationFileLink(TimeStampedModel):
    quotation_version = models.ForeignKey(QuotationVersion, on_delete=models.PROTECT, related_name="file_links")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="quotation_links")
    file_role = models.CharField(max_length=50, validators=[uppercase_code_validator])

    class Meta:
        db_table = "quotation_file_link"
        constraints = [
            models.UniqueConstraint(
                fields=["quotation_version", "business_file"],
                name="quotation_file_link_uniq",
            ),
        ]
