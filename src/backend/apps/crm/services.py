from django.db import transaction

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.customers.services import model_snapshot, write_customer_timeline

from .models import (
    CommunicationContactParticipant,
    CommunicationEmployeeParticipant,
    CommunicationFileLink,
    CommunicationInquiryLink,
    CommunicationQuotationVersionLink,
    CommunicationSampleRequestLink,
    CustomerCommunication,
)


COMMUNICATION_FIELDS = [
    "customer_account",
    "communication_type",
    "direction",
    "subject",
    "content",
    "occurred_at",
    "source_system",
    "external_id",
]


@transaction.atomic
def create_communication(*, validated_data, actor_employee, request):
    participant_employees = validated_data.pop("participant_employees", [])
    participant_contacts = validated_data.pop("participant_contacts", [])
    inquiry = validated_data.pop("inquiry", None)
    quotation_version = validated_data.pop("quotation_version", None)
    sample_request = validated_data.pop("sample_request", None)
    business_files = validated_data.pop("business_files", [])

    communication = CustomerCommunication.objects.create(
        created_by_employee=actor_employee,
        **validated_data,
    )
    if actor_employee:
        CommunicationEmployeeParticipant.objects.create(
            communication=communication,
            employee=actor_employee,
            participant_role="OWNER",
        )
    CommunicationEmployeeParticipant.objects.bulk_create(
        [
            CommunicationEmployeeParticipant(
                communication=communication,
                employee=employee,
                participant_role="PARTICIPANT",
            )
            for employee in participant_employees
            if actor_employee is None or employee.pk != actor_employee.pk
        ]
    )
    CommunicationContactParticipant.objects.bulk_create(
        [
            CommunicationContactParticipant(
                communication=communication,
                customer_contact=contact,
                participant_role="RECIPIENT",
            )
            for contact in participant_contacts
        ]
    )
    if inquiry:
        CommunicationInquiryLink.objects.create(communication=communication, inquiry=inquiry)
    if quotation_version:
        CommunicationQuotationVersionLink.objects.create(
            communication=communication,
            quotation_version=quotation_version,
        )
    if sample_request:
        CommunicationSampleRequestLink.objects.create(
            communication=communication,
            sample_request=sample_request,
        )
    CommunicationFileLink.objects.bulk_create(
        [
            CommunicationFileLink(
                communication=communication,
                business_file=business_file,
                file_role="ATTACHMENT",
            )
            for business_file in business_files
        ]
    )

    after_data = model_snapshot(communication, COMMUNICATION_FIELDS)
    after_data.update(
        {
            "employee_participant_ids": [str(employee.pk) for employee in participant_employees],
            "contact_participant_ids": [str(contact.pk) for contact in participant_contacts],
            "inquiry_id": str(inquiry.pk) if inquiry else None,
            "quotation_version_id": str(quotation_version.pk) if quotation_version else None,
            "sample_request_id": str(sample_request.pk) if sample_request else None,
            "file_ids": [str(business_file.pk) for business_file in business_files],
        }
    )
    write_audit_log(
        object_type="CUSTOMER_COMMUNICATION",
        object_id=communication.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=communication.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=after_data,
        request=request,
    )
    write_customer_timeline(
        customer=communication.customer_account,
        event_type="COMMUNICATION_CREATED",
        title=communication.subject or "新增客户沟通记录",
        summary=communication.content[:500],
        source_type="CUSTOMER_COMMUNICATION",
        source_id=communication.pk,
        actor_employee=actor_employee,
        occurred_at=communication.occurred_at,
    )
    return communication


@transaction.atomic
def update_communication(*, communication, validated_data, actor_employee, request):
    communication = CustomerCommunication.objects.select_for_update().get(pk=communication.pk)
    require_matching_etag(request, communication)
    before_data = model_snapshot(communication, COMMUNICATION_FIELDS)
    for field_name, value in validated_data.items():
        setattr(communication, field_name, value)
    communication.save(update_fields=[*validated_data.keys(), "updated_at"])
    write_audit_log(
        object_type="CUSTOMER_COMMUNICATION",
        object_id=communication.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=communication.customer_account_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(communication, COMMUNICATION_FIELDS),
        request=request,
    )
    write_customer_timeline(
        customer=communication.customer_account,
        event_type="COMMUNICATION_UPDATED",
        title=communication.subject or "客户沟通记录已修正",
        source_type="CUSTOMER_COMMUNICATION",
        source_id=communication.pk,
        actor_employee=actor_employee,
    )
    return communication

