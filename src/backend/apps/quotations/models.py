import uuid

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
    # 创建询盘报价时用于抵御网络重试；普通报价保持为空。
    creation_idempotency_key = models.CharField(max_length=64, blank=True)

    class Meta:
        db_table = "quotation"
        permissions = [
            ("issue_quotation", "可签发报价"),
            ("dispatch_quotation", "可发送报价"),
            ("accept_quotation", "可确认报价被接受"),
            ("approve_quotation", "可审批报价"),
            ("export_quotation", "可导出报价列表"),
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
            models.UniqueConstraint(
                fields=["creation_idempotency_key"],
                condition=~Q(creation_idempotency_key=""),
                name="quotation_create_idempotency_uniq",
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
    parent_version = models.ForeignKey(
        "self",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="child_versions",
    )
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
    customer_requirement_snapshot = models.JSONField(default=dict, blank=True)
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
    source_inquiry_item = models.ForeignKey(
        "inquiries.InquiryItem",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_lines",
    )
    lineage_id = models.UUIDField(default=uuid.uuid4, editable=False, db_index=True, null=True, blank=True)
    line_number = models.PositiveIntegerField()
    product_description_snapshot = models.CharField(max_length=500)
    specification_snapshot = models.TextField(blank=True)
    # 颜色从规格文本中独立出来，允许询盘/报价阶段保留客户原始填写值。
    # 允许为空以兼容历史报价明细；后续新流程可按需填写。
    color_snapshot = models.TextField(null=True, blank=True)
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    discount_rate = models.DecimalField(max_digits=7, decimal_places=6, default=0)
    line_total = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    notes = models.TextField(blank=True)
    product_image = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_line_product_images",
    )

    class Meta:
        db_table = "quotation_line"
        ordering = ["quotation_version", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["quotation_version", "line_number"], name="quotation_line_number_uniq"),
            models.CheckConstraint(condition=Q(quantity__gt=0), name="quotation_line_qty_positive"),
            models.CheckConstraint(
                condition=Q(unit_price__isnull=True) | Q(unit_price__gte=0),
                name="quotation_line_price_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(discount_rate__gte=0) & Q(discount_rate__lte=1),
                name="quotation_line_discount_range",
            ),
            models.CheckConstraint(
                condition=Q(line_total__isnull=True) | Q(line_total__gte=0),
                name="quotation_line_total_nonneg",
            ),
        ]


class QuotationPriceBasis(TimeStampedModel):
    """同一报价版本下的一种价格口径，例如 EXW 宁波、FOB 宁波或 CIF 汉堡。"""

    quotation_version = models.ForeignKey(
        QuotationVersion,
        on_delete=models.PROTECT,
        related_name="price_bases",
    )
    label = models.CharField(max_length=120)
    incoterm_code = models.CharField(max_length=20, validators=[uppercase_code_validator])
    named_place = models.CharField(max_length=180)
    currency_code = models.CharField(max_length=3, validators=[currency_code_validator])
    is_default = models.BooleanField(default=False)
    sort_order = models.PositiveSmallIntegerField(default=1)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "quotation_price_basis"
        ordering = ["quotation_version", "sort_order", "id"]
        constraints = [
            models.UniqueConstraint(
                fields=["quotation_version", "label"],
                name="quote_price_basis_label_uniq",
            ),
            models.UniqueConstraint(
                fields=["quotation_version"],
                condition=Q(is_default=True),
                name="quote_price_basis_default_uniq",
            ),
            models.UniqueConstraint(
                fields=["quotation_version", "sort_order"],
                name="quote_price_basis_sort_uniq",
            ),
        ]


class QuotationLinePrice(TimeStampedModel):
    quotation_line = models.ForeignKey(
        QuotationLine,
        on_delete=models.PROTECT,
        related_name="basis_prices",
    )
    price_basis = models.ForeignKey(
        QuotationPriceBasis,
        on_delete=models.PROTECT,
        related_name="line_prices",
    )
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)
    surcharge_note = models.CharField(max_length=500, blank=True)
    is_manual_override = models.BooleanField(default=False)
    override_reason = models.CharField(max_length=500, blank=True)

    class Meta:
        db_table = "quotation_line_price"
        constraints = [
            models.UniqueConstraint(
                fields=["quotation_line", "price_basis"],
                name="quote_line_price_basis_uniq",
            ),
            models.CheckConstraint(
                condition=Q(unit_price__gte=0),
                name="quote_line_basis_price_nonneg",
            ),
            models.CheckConstraint(
                condition=Q(is_manual_override=False) | ~Q(override_reason=""),
                name="quote_line_override_reason_required",
            ),
        ]

    def clean(self):
        super().clean()
        if (
            self.quotation_line_id
            and self.price_basis_id
            and self.quotation_line.quotation_version_id != self.price_basis.quotation_version_id
        ):
            raise ValidationError({"price_basis": "价格口径必须属于报价明细所在版本。"})


class QuotationContainerConfig(ArchivableModel):
    """版本化集装箱参数，不将 20GP/40GP/40HQ 样例值写死到业务代码。"""
    container_type_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    config_version = models.PositiveIntegerField(default=1)
    effective_volume_cbm = models.DecimalField(max_digits=12, decimal_places=4)
    default_load_factor = models.DecimalField(max_digits=7, decimal_places=6)
    is_active = models.BooleanField(default=True)

    class Meta:
        db_table = "quotation_container_config"
        constraints = [
            models.UniqueConstraint(fields=["container_type_code", "config_version"], name="quote_container_config_version_uniq"),
            models.CheckConstraint(condition=Q(effective_volume_cbm__gt=0), name="quote_container_config_volume_positive"),
            models.CheckConstraint(condition=Q(default_load_factor__gt=0) & Q(default_load_factor__lte=1), name="quote_container_config_load_factor_valid"),
        ]


class QuotationLinePackaging(TimeStampedModel):
    quotation_line = models.OneToOneField(QuotationLine, on_delete=models.PROTECT, related_name="packaging")
    length_cm = models.DecimalField(max_digits=12, decimal_places=4)
    width_cm = models.DecimalField(max_digits=12, decimal_places=4)
    height_cm = models.DecimalField(max_digits=12, decimal_places=4)
    pieces_per_carton = models.PositiveIntegerField()
    carton_count = models.PositiveIntegerField()
    gross_weight_kg = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    net_weight_kg = models.DecimalField(max_digits=12, decimal_places=4, null=True, blank=True)
    carton_cbm = models.DecimalField(max_digits=18, decimal_places=6)

    class Meta:
        db_table = "quotation_line_packaging"
        constraints = [
            models.CheckConstraint(condition=Q(length_cm__gt=0) & Q(width_cm__gt=0) & Q(height_cm__gt=0), name="quote_packaging_dimensions_positive"),
            models.CheckConstraint(condition=Q(pieces_per_carton__gt=0) & Q(carton_count__gt=0), name="quote_packaging_counts_positive"),
            models.CheckConstraint(condition=Q(carton_cbm__gt=0), name="quote_packaging_cbm_positive"),
        ]


class QuotationContainerTier(TimeStampedModel):
    quotation_line = models.ForeignKey(QuotationLine, on_delete=models.PROTECT, related_name="container_tiers")
    tier_number = models.PositiveIntegerField()
    # 旧数量档仍可追溯到全局参数；新数量档按报价行保存快照，不再修改或依赖全局参数。
    container_config = models.ForeignKey(
        QuotationContainerConfig,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_tiers",
    )
    container_type_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    effective_volume_cbm = models.DecimalField(max_digits=12, decimal_places=4)
    load_factor = models.DecimalField(max_digits=7, decimal_places=6)
    auto_carton_count = models.PositiveIntegerField()
    auto_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    manual_carton_count = models.PositiveIntegerField(null=True, blank=True)
    override_reason = models.TextField(blank=True)
    final_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_price = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "quotation_container_tier"
        ordering = ["quotation_line", "tier_number"]
        constraints = [
            models.UniqueConstraint(fields=["quotation_line", "tier_number"], name="quote_container_tier_number_uniq"),
            models.CheckConstraint(condition=Q(effective_volume_cbm__gt=0), name="quote_container_tier_volume_positive"),
            models.CheckConstraint(condition=Q(load_factor__gt=0) & Q(load_factor__lte=1), name="quote_container_tier_load_factor_valid"),
            models.CheckConstraint(condition=Q(final_quantity__gte=0), name="quote_container_tier_final_quantity_nonneg"),
            models.CheckConstraint(condition=Q(unit_price__gte=0), name="quote_container_tier_unit_price_nonneg"),
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


class QuotationEmailDispatchAttemptStatus(models.TextChoices):
    PROCESSING = "PROCESSING", "发送处理中"
    ACCEPTED = "ACCEPTED", "邮件服务已接受"
    FAILED = "FAILED", "确认未发送"
    UNCERTAIN = "UNCERTAIN", "结果待核对"


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
    is_simulated = models.BooleanField(default=False)
    price_basis = models.ForeignKey(
        QuotationPriceBasis,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="dispatch_records",
    )
    evidence_file = models.ForeignKey(
        "files.BusinessFile",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_dispatch_evidence",
    )

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

    def clean(self):
        super().clean()
        if self.price_basis_id and self.price_basis.quotation_version_id != self.quotation_version_id:
            raise ValidationError({"price_basis": "发送价格口径必须属于当前报价版本。"})


class QuotationEmailDispatchAttempt(TimeStampedModel):
    """邮件外部副作用的持久化尝试，用于超时恢复和幂等重放。"""

    quotation_version = models.ForeignKey(
        QuotationVersion,
        on_delete=models.PROTECT,
        related_name="email_dispatch_attempts",
    )
    price_basis = models.ForeignKey(
        QuotationPriceBasis,
        on_delete=models.PROTECT,
        related_name="email_dispatch_attempts",
    )
    quotation_document = models.ForeignKey(
        QuotationDocument,
        on_delete=models.PROTECT,
        related_name="email_dispatch_attempts",
    )
    requested_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="quotation_email_dispatch_attempts",
    )
    idempotency_key = models.UUIDField()
    payload_hash = models.CharField(max_length=64)
    status = models.CharField(
        max_length=20,
        choices=QuotationEmailDispatchAttemptStatus.choices,
        default=QuotationEmailDispatchAttemptStatus.PROCESSING,
    )
    recipient = models.EmailField(max_length=254)
    cc_snapshot = models.JSONField(default=list, blank=True)
    subject = models.CharField(max_length=250)
    body_html = models.TextField()
    recipient_snapshot = models.JSONField(default=dict)
    attachment_snapshot = models.JSONField(default=dict)
    follow_up_due_at = models.DateTimeField(null=True, blank=True)
    error_message = models.TextField(blank=True)
    dispatch_record = models.OneToOneField(
        QuotationDispatchRecord,
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="email_attempt",
    )
    resolved_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="resolved_quotation_email_dispatch_attempts",
    )
    resolved_at = models.DateTimeField(null=True, blank=True)
    resolution_note = models.TextField(blank=True)

    class Meta:
        db_table = "quotation_email_dispatch_attempt"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=QuotationEmailDispatchAttemptStatus.values),
                name="quote_email_attempt_status_valid",
            ),
            models.UniqueConstraint(
                fields=["quotation_version", "idempotency_key"],
                name="quote_email_attempt_idem_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["quotation_version", "-created_at", "-id"],
                name="q_email_attempt_hist_idx",
            ),
            models.Index(
                fields=["status", "updated_at", "id"],
                condition=Q(status__in=[
                    QuotationEmailDispatchAttemptStatus.PROCESSING,
                    QuotationEmailDispatchAttemptStatus.UNCERTAIN,
                ]),
                name="q_email_attempt_open_idx",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.price_basis_id and self.price_basis.quotation_version_id != self.quotation_version_id:
            errors["price_basis"] = "邮件价格口径必须属于当前报价版本。"
        if self.quotation_document_id and self.quotation_document.quotation_version_id != self.quotation_version_id:
            errors["quotation_document"] = "邮件附件必须属于当前报价版本。"
        if self.dispatch_record_id and self.dispatch_record.quotation_version_id != self.quotation_version_id:
            errors["dispatch_record"] = "发送记录必须属于当前报价版本。"
        if errors:
            raise ValidationError(errors)


class QuotationAcceptanceSource(models.TextChoices):
    EMAIL = "EMAIL", "邮件"
    PHONE = "PHONE", "电话"
    MEETING = "MEETING", "会议"
    OTHER = "OTHER", "其他"


class QuotationAcceptance(TimeStampedModel):
    quotation = models.OneToOneField(
        Quotation,
        on_delete=models.PROTECT,
        related_name="acceptance",
    )
    quotation_version = models.ForeignKey(
        QuotationVersion,
        on_delete=models.PROTECT,
        related_name="acceptances",
    )
    price_basis = models.ForeignKey(
        QuotationPriceBasis,
        on_delete=models.PROTECT,
        related_name="acceptances",
    )
    customer_contact = models.ForeignKey(
        "customers.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="quotation_acceptances",
    )
    accepted_at = models.DateTimeField()
    source = models.CharField(max_length=20, choices=QuotationAcceptanceSource.choices)
    note = models.TextField(blank=True)
    recorded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_quotation_acceptances",
    )

    class Meta:
        db_table = "quotation_acceptance"
        constraints = [
            models.CheckConstraint(
                condition=Q(source__in=QuotationAcceptanceSource.values),
                name="quotation_acceptance_source_valid",
            ),
        ]

    def clean(self):
        super().clean()
        errors = {}
        if self.quotation_version_id and self.quotation_version.quotation_id != self.quotation_id:
            errors["quotation_version"] = "接受版本必须属于当前报价。"
        if self.price_basis_id and self.price_basis.quotation_version_id != self.quotation_version_id:
            errors["price_basis"] = "接受价格口径必须属于接受版本。"
        if self.customer_contact_id and self.customer_contact.customer_account_id != self.quotation.customer_account_id:
            errors["customer_contact"] = "确认联系人必须属于报价客户。"
        if errors:
            raise ValidationError(errors)


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
