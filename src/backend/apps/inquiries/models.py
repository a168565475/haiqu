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


class InquiryStatus(models.TextChoices):
    DRAFT = "DRAFT", "草稿"
    SUBMITTED = "SUBMITTED", "已提交"
    IN_PROGRESS = "IN_PROGRESS", "处理中"
    QUOTED = "QUOTED", "已报价"
    CLOSED = "CLOSED", "已关闭"
    CANCELLED = "CANCELLED", "已取消"


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
        on_delete=models.PROTECT,
        related_name="owned_inquiries",
    )
    inquiry_number = models.CharField(max_length=50, unique=True, validators=[uppercase_code_validator])
    status = models.CharField(max_length=20, choices=InquiryStatus.choices, default=InquiryStatus.DRAFT)
    inquiry_source = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    subject = models.CharField(max_length=250)
    description = models.TextField(blank=True)
    received_at = models.DateTimeField()
    requested_due_at = models.DateTimeField(null=True, blank=True)
    submitted_at = models.DateTimeField(null=True, blank=True)
    source_system = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    external_id = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "inquiry"
        constraints = [
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
        ]
        indexes = [
            models.Index(
                fields=["owner_employee", "status", "-received_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="inquiry_owner_status_idx",
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
    quantity = models.DecimalField(max_digits=18, decimal_places=4)
    unit_code = models.CharField(max_length=30, validators=[uppercase_code_validator])
    target_unit_price = models.DecimalField(max_digits=18, decimal_places=4, null=True, blank=True)
    target_currency_code = models.CharField(max_length=3, blank=True, validators=[currency_code_validator])
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

    class Meta:
        db_table = "inquiry_sla_link"


class InquiryFileLink(TimeStampedModel):
    inquiry = models.ForeignKey(Inquiry, on_delete=models.PROTECT, related_name="file_links")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="inquiry_links")
    file_role = models.CharField(max_length=50, validators=[uppercase_code_validator])

    class Meta:
        db_table = "inquiry_file_link"
        constraints = [
            models.UniqueConstraint(fields=["inquiry", "business_file"], name="inquiry_file_link_uniq"),
        ]
