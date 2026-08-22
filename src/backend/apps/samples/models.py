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


class SampleRequestStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    PENDING = "PENDING", "待处理"
    PREPARING = "PREPARING", "准备中"
    SHIPPED = "SHIPPED", "已寄出"
    FEEDBACK_PENDING = "FEEDBACK_PENDING", "待反馈"
    COMPLETED = "COMPLETED", "已完成"
    CANCELLED = "CANCELLED", "已取消"


class SampleRequest(ArchivableModel):
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    transaction_entity = models.ForeignKey(
        "customers.CustomerTransactionEntity",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    customer_contact = models.ForeignKey(
        "customers.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    owner_employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="owned_sample_requests",
    )
    source_inquiry = models.ForeignKey(
        "inquiries.Inquiry",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    source_quotation_version = models.ForeignKey(
        "quotations.QuotationVersion",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_requests",
    )
    request_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    status = models.CharField(
        max_length=30,
        choices=SampleRequestStatus.choices,
        default=SampleRequestStatus.DRAFT,
    )
    purpose = models.TextField(blank=True)
    requested_at = models.DateTimeField()
    requested_due_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sample_request"
        permissions = [
            ("decide_sample_fee", "可决定样品费用"),
            ("ship_sample", "可寄送样品"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=SampleRequestStatus.values),
                name="sample_request_status_valid",
            ),
            models.CheckConstraint(
                condition=uppercase_code_condition("request_number"),
                name="sample_request_number_uppercase",
            ),
            models.CheckConstraint(
                condition=Q(source_inquiry__isnull=True) | Q(source_quotation_version__isnull=True),
                name="sample_request_one_source_max",
            ),
        ]
        indexes = [
            models.Index(
                fields=["owner_employee", "status", "-updated_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="sample_owner_status_idx",
            ),
            models.Index(
                fields=["status", "requested_at", "id"],
                condition=Q(
                    archived_at__isnull=True,
                    status__in=[
                        SampleRequestStatus.PENDING,
                        SampleRequestStatus.PREPARING,
                        SampleRequestStatus.SHIPPED,
                        SampleRequestStatus.FEEDBACK_PENDING,
                    ],
                ),
                name="sample_processing_queue_idx",
            ),
            models.Index(
                fields=["customer_account", "-requested_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="sample_customer_idx",
            ),
            models.Index(
                fields=["source_inquiry", "-requested_at", "-id"],
                condition=Q(source_inquiry__isnull=False),
                name="sample_inquiry_source_idx",
            ),
            models.Index(
                fields=["source_quotation_version", "-requested_at", "-id"],
                condition=Q(source_quotation_version__isnull=False),
                name="sample_quote_source_idx",
            ),
        ]

    def __str__(self):
        return self.request_number

    def clean(self):
        super().clean()
        errors = {}
        if self.transaction_entity_id and self.transaction_entity.customer_account_id != self.customer_account_id:
            errors["transaction_entity"] = "样品交易主体必须属于同一客户账户。"
        if self.customer_contact_id and self.customer_contact.customer_account_id != self.customer_account_id:
            errors["customer_contact"] = "样品联系人必须属于同一客户账户。"
        if self.source_inquiry_id and self.source_inquiry.customer_account_id != self.customer_account_id:
            errors["source_inquiry"] = "来源询价必须属于同一客户账户。"
        if (
            self.source_quotation_version_id
            and self.source_quotation_version.quotation.customer_account_id != self.customer_account_id
        ):
            errors["source_quotation_version"] = "来源报价版本必须属于同一客户账户。"
        if errors:
            raise ValidationError(errors)


class SampleItem(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="items")
    line_number = models.PositiveIntegerField()
    product_description_snapshot = models.CharField(max_length=500)
    specification_snapshot = models.TextField(blank=True)
    requested_quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sample_item"
        ordering = ["sample_request", "line_number"]
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "line_number"], name="sample_item_line_uniq"),
            models.CheckConstraint(condition=Q(requested_quantity__gt=0), name="sample_item_qty_positive"),
        ]


class SampleFeeDecision(models.TextChoices):
    PENDING = "PENDING", "待决定"
    FREE = "FREE", "免费"
    PAID = "PAID", "收费"
    WAIVED = "WAIVED", "已减免"


class FeeVerificationStatus(models.TextChoices):
    NOT_REQUIRED = "NOT_REQUIRED", "无需确认"
    EVIDENCE_UPLOADED = "EVIDENCE_UPLOADED", "已上传凭证"
    MANUALLY_CONFIRMED = "MANUALLY_CONFIRMED", "已人工确认"
    REJECTED = "REJECTED", "凭证无效"


class SampleFeeRecord(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="fee_records")
    fee_decision = models.CharField(
        max_length=20,
        choices=SampleFeeDecision.choices,
        default=SampleFeeDecision.PENDING,
    )
    amount = models.DecimalField(max_digits=18, decimal_places=4, default=0)
    currency_code = models.CharField(max_length=3, validators=[currency_code_validator])
    verification_status = models.CharField(
        max_length=30,
        choices=FeeVerificationStatus.choices,
        default=FeeVerificationStatus.NOT_REQUIRED,
    )
    decision_reason = models.TextField(blank=True)
    decided_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_fee_decisions",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    superseded_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        db_table = "sample_fee_record"
        constraints = [
            models.CheckConstraint(
                condition=Q(fee_decision__in=SampleFeeDecision.values),
                name="sample_fee_decision_valid",
            ),
            models.CheckConstraint(
                condition=Q(verification_status__in=FeeVerificationStatus.values),
                name="sample_fee_verify_status_valid",
            ),
            models.CheckConstraint(condition=Q(amount__gte=0), name="sample_fee_amount_nonneg"),
            models.CheckConstraint(
                condition=Q(fee_decision=SampleFeeDecision.PAID, amount__gt=0)
                | Q(fee_decision__in=[SampleFeeDecision.FREE, SampleFeeDecision.WAIVED], amount=0)
                | Q(fee_decision=SampleFeeDecision.PENDING),
                name="sample_fee_decision_amount_match",
            ),
            models.UniqueConstraint(
                fields=["sample_request"],
                condition=Q(superseded_at__isnull=True),
                name="sample_fee_current_record_uniq",
            ),
        ]


class SampleShipmentStatus(models.TextChoices):
    PREPARING = "PREPARING", "准备中"
    SHIPPED = "SHIPPED", "已寄出"
    DELIVERED = "DELIVERED", "已送达"
    EXCEPTION = "EXCEPTION", "异常"
    CANCELLED = "CANCELLED", "已取消"


class SampleShipment(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="shipments")
    shipped_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_shipments",
    )
    status = models.CharField(
        max_length=20,
        choices=SampleShipmentStatus.choices,
        default=SampleShipmentStatus.PREPARING,
    )
    carrier_code = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    tracking_number = models.CharField(max_length=150, blank=True)
    recipient_snapshot = models.JSONField(default=dict)
    address_snapshot = models.JSONField(default=dict)
    shipped_at = models.DateTimeField(null=True, blank=True)
    delivered_at = models.DateTimeField(null=True, blank=True)
    fee_warning_acknowledged = models.BooleanField(default=False)
    fee_warning_acknowledged_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="sample_fee_warnings_acknowledged",
    )
    fee_warning_acknowledged_at = models.DateTimeField(null=True, blank=True)
    notes = models.TextField(blank=True)

    class Meta:
        db_table = "sample_shipment"
        constraints = [
            models.CheckConstraint(
                condition=Q(status__in=SampleShipmentStatus.values),
                name="sample_shipment_status_valid",
            ),
        ]
        indexes = [
            models.Index(fields=["sample_request", "-shipped_at", "-id"], name="sample_shipment_history_idx"),
            models.Index(
                fields=["carrier_code", "tracking_number"],
                condition=~Q(tracking_number=""),
                name="sample_tracking_lookup_idx",
            ),
        ]


class SampleShipmentItem(TimeStampedModel):
    sample_shipment = models.ForeignKey(SampleShipment, on_delete=models.PROTECT, related_name="items")
    sample_item = models.ForeignKey(SampleItem, on_delete=models.PROTECT, related_name="shipment_items")
    shipped_quantity = models.DecimalField(max_digits=18, decimal_places=4)

    class Meta:
        db_table = "sample_shipment_item"
        constraints = [
            models.UniqueConstraint(
                fields=["sample_shipment", "sample_item"],
                name="sample_shipment_item_uniq",
            ),
            models.CheckConstraint(condition=Q(shipped_quantity__gt=0), name="sample_ship_item_qty_positive"),
        ]

    def clean(self):
        super().clean()
        if (
            self.sample_shipment_id
            and self.sample_item_id
            and self.sample_shipment.sample_request_id != self.sample_item.sample_request_id
        ):
            raise ValidationError({"sample_item": "寄送明细必须属于同一个样品申请。"})


class SampleFeedbackType(models.TextChoices):
    POSITIVE = "POSITIVE", "正向"
    NEUTRAL = "NEUTRAL", "一般"
    NEGATIVE = "NEGATIVE", "负向"
    FOLLOW_UP = "FOLLOW_UP", "需继续跟进"


class SampleFeedback(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="feedback_records")
    customer_contact = models.ForeignKey(
        "customers.CustomerContact",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="sample_feedback_records",
    )
    recorded_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="recorded_sample_feedback",
    )
    feedback_type = models.CharField(max_length=20, choices=SampleFeedbackType.choices)
    feedback_content = models.TextField()
    occurred_at = models.DateTimeField()

    class Meta:
        db_table = "sample_feedback"
        indexes = [models.Index(fields=["sample_request", "-occurred_at", "-id"], name="sample_feedback_history_idx")]


class SampleTaskLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="task_links")
    business_task = models.ForeignKey("workflow.BusinessTask", on_delete=models.PROTECT, related_name="sample_links")
    is_primary_source = models.BooleanField(default=True)

    class Meta:
        db_table = "sample_task_link"
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "business_task"], name="sample_task_link_uniq"),
            models.UniqueConstraint(
                fields=["business_task"],
                condition=Q(is_primary_source=True),
                name="sample_task_primary_uniq",
            ),
        ]


class SampleSlaLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="sla_links")
    sla_tracking = models.OneToOneField(
        "workflow.SlaTracking",
        on_delete=models.PROTECT,
        related_name="sample_link",
    )

    class Meta:
        db_table = "sample_sla_link"


class SampleApprovalLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="approval_links")
    approval_request = models.OneToOneField(
        "workflow.ApprovalRequest",
        on_delete=models.PROTECT,
        related_name="sample_link",
    )

    class Meta:
        db_table = "sample_approval_link"


class SampleFileLink(TimeStampedModel):
    sample_request = models.ForeignKey(SampleRequest, on_delete=models.PROTECT, related_name="file_links")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="sample_links")
    file_role = models.CharField(max_length=50, validators=[uppercase_code_validator])

    class Meta:
        db_table = "sample_file_link"
        constraints = [
            models.UniqueConstraint(fields=["sample_request", "business_file"], name="sample_file_link_uniq"),
        ]
