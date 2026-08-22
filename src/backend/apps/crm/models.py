from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.core.models import ArchivableModel, TimeStampedModel, uppercase_code_validator


class CommunicationDirection(models.TextChoices):
    INBOUND = "INBOUND", "客户发起"
    OUTBOUND = "OUTBOUND", "员工发起"
    INTERNAL = "INTERNAL", "内部记录"


class CustomerCommunication(ArchivableModel):
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        related_name="communications",
    )
    created_by_employee = models.ForeignKey(
        "organizations.Employee",
        null=True,
        blank=True,
        on_delete=models.SET_NULL,
        related_name="created_communications",
    )
    communication_type = models.CharField(max_length=50, validators=[uppercase_code_validator])
    direction = models.CharField(max_length=20, choices=CommunicationDirection.choices)
    subject = models.CharField(max_length=250, blank=True)
    content = models.TextField()
    occurred_at = models.DateTimeField()
    source_system = models.CharField(max_length=50, blank=True, validators=[uppercase_code_validator])
    external_id = models.CharField(max_length=150, blank=True)

    class Meta:
        db_table = "customer_communication"
        constraints = [
            models.CheckConstraint(
                condition=Q(source_system="", external_id="")
                | (~Q(source_system="") & ~Q(external_id="")),
                name="communication_source_pair_consistent",
            ),
            models.UniqueConstraint(
                fields=["source_system", "external_id"],
                condition=~Q(source_system="") & ~Q(external_id=""),
                name="communication_external_source_uniq",
            ),
        ]
        indexes = [
            models.Index(
                fields=["customer_account", "-occurred_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="communication_customer_idx",
            ),
            models.Index(
                fields=["created_by_employee", "-occurred_at", "-id"],
                condition=Q(archived_at__isnull=True),
                name="communication_creator_idx",
            ),
        ]


class ParticipantRole(models.TextChoices):
    OWNER = "OWNER", "负责人"
    PARTICIPANT = "PARTICIPANT", "参与人"
    RECIPIENT = "RECIPIENT", "接收人"


class CommunicationEmployeeParticipant(TimeStampedModel):
    communication = models.ForeignKey(
        CustomerCommunication,
        on_delete=models.PROTECT,
        related_name="employee_participants",
    )
    employee = models.ForeignKey(
        "organizations.Employee",
        on_delete=models.PROTECT,
        related_name="communication_participations",
    )
    participant_role = models.CharField(max_length=20, choices=ParticipantRole.choices)

    class Meta:
        db_table = "communication_employee_participant"
        constraints = [
            models.UniqueConstraint(fields=["communication", "employee"], name="comm_employee_participant_uniq"),
        ]
        indexes = [models.Index(fields=["employee", "communication"], name="comm_employee_lookup_idx")]


class CommunicationContactParticipant(TimeStampedModel):
    communication = models.ForeignKey(
        CustomerCommunication,
        on_delete=models.PROTECT,
        related_name="contact_participants",
    )
    customer_contact = models.ForeignKey(
        "customers.CustomerContact",
        on_delete=models.PROTECT,
        related_name="communication_participations",
    )
    participant_role = models.CharField(max_length=20, choices=ParticipantRole.choices)

    class Meta:
        db_table = "communication_contact_participant"
        constraints = [
            models.UniqueConstraint(
                fields=["communication", "customer_contact"],
                name="comm_contact_participant_uniq",
            ),
        ]
        indexes = [models.Index(fields=["customer_contact", "communication"], name="comm_contact_lookup_idx")]

    def clean(self):
        super().clean()
        if (
            self.communication_id
            and self.customer_contact_id
            and self.communication.customer_account_id != self.customer_contact.customer_account_id
        ):
            raise ValidationError({"customer_contact": "沟通联系人必须属于同一客户账户。"})


class CommunicationInquiryLink(TimeStampedModel):
    communication = models.ForeignKey(CustomerCommunication, on_delete=models.PROTECT, related_name="inquiry_links")
    inquiry = models.ForeignKey("inquiries.Inquiry", on_delete=models.PROTECT, related_name="communication_links")

    class Meta:
        db_table = "communication_inquiry_link"
        constraints = [
            models.UniqueConstraint(fields=["communication", "inquiry"], name="comm_inquiry_link_uniq"),
        ]
        indexes = [models.Index(fields=["inquiry", "communication"], name="comm_inquiry_lookup_idx")]

    def clean(self):
        super().clean()
        if self.communication_id and self.inquiry_id and self.communication.customer_account_id != self.inquiry.customer_account_id:
            raise ValidationError({"inquiry": "关联询价必须属于同一客户账户。"})


class CommunicationQuotationVersionLink(TimeStampedModel):
    communication = models.ForeignKey(CustomerCommunication, on_delete=models.PROTECT, related_name="quotation_links")
    quotation_version = models.ForeignKey(
        "quotations.QuotationVersion",
        on_delete=models.PROTECT,
        related_name="communication_links",
    )

    class Meta:
        db_table = "communication_quotation_version_link"
        constraints = [
            models.UniqueConstraint(
                fields=["communication", "quotation_version"],
                name="comm_quote_version_link_uniq",
            ),
        ]
        indexes = [models.Index(fields=["quotation_version", "communication"], name="comm_quote_lookup_idx")]

    def clean(self):
        super().clean()
        if (
            self.communication_id
            and self.quotation_version_id
            and self.communication.customer_account_id
            != self.quotation_version.quotation.customer_account_id
        ):
            raise ValidationError({"quotation_version": "关联报价版本必须属于同一客户账户。"})


class CommunicationSampleRequestLink(TimeStampedModel):
    communication = models.ForeignKey(CustomerCommunication, on_delete=models.PROTECT, related_name="sample_links")
    sample_request = models.ForeignKey(
        "samples.SampleRequest",
        on_delete=models.PROTECT,
        related_name="communication_links",
    )

    class Meta:
        db_table = "communication_sample_request_link"
        constraints = [
            models.UniqueConstraint(
                fields=["communication", "sample_request"],
                name="comm_sample_request_link_uniq",
            ),
        ]
        indexes = [models.Index(fields=["sample_request", "communication"], name="comm_sample_lookup_idx")]

    def clean(self):
        super().clean()
        if (
            self.communication_id
            and self.sample_request_id
            and self.communication.customer_account_id != self.sample_request.customer_account_id
        ):
            raise ValidationError({"sample_request": "关联样品申请必须属于同一客户账户。"})


class CustomerTimelineEvent(TimeStampedModel):
    customer_account = models.ForeignKey(
        "customers.CustomerAccount",
        on_delete=models.PROTECT,
        related_name="timeline_events",
    )
    event_key = models.CharField(max_length=200, unique=True)
    source_type = models.CharField(max_length=80, validators=[uppercase_code_validator])
    source_id = models.UUIDField()
    event_type = models.CharField(max_length=80, validators=[uppercase_code_validator])
    title = models.CharField(max_length=250)
    summary = models.TextField(blank=True)
    occurred_at = models.DateTimeField()
    event_data = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "customer_timeline_event"
        indexes = [
            models.Index(fields=["customer_account", "-occurred_at", "-id"], name="timeline_customer_idx"),
            models.Index(fields=["source_type", "source_id"], name="timeline_source_idx"),
        ]


class CommunicationTaskLink(TimeStampedModel):
    communication = models.ForeignKey(CustomerCommunication, on_delete=models.PROTECT, related_name="task_links")
    business_task = models.ForeignKey(
        "workflow.BusinessTask",
        on_delete=models.PROTECT,
        related_name="communication_links",
    )
    is_primary_source = models.BooleanField(default=True)

    class Meta:
        db_table = "communication_task_link"
        constraints = [
            models.UniqueConstraint(
                fields=["communication", "business_task"],
                name="communication_task_link_uniq",
            ),
            models.UniqueConstraint(
                fields=["business_task"],
                condition=Q(is_primary_source=True),
                name="communication_task_primary_uniq",
            ),
        ]


class CommunicationFileLink(TimeStampedModel):
    communication = models.ForeignKey(CustomerCommunication, on_delete=models.PROTECT, related_name="file_links")
    business_file = models.ForeignKey("files.BusinessFile", on_delete=models.PROTECT, related_name="communication_links")
    file_role = models.CharField(max_length=50, validators=[uppercase_code_validator])

    class Meta:
        db_table = "communication_file_link"
        constraints = [
            models.UniqueConstraint(
                fields=["communication", "business_file"],
                name="communication_file_link_uniq",
            ),
        ]
