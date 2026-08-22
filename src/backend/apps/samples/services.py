from datetime import timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.customers.services import model_snapshot, write_customer_timeline
from apps.workflow.models import SlaPolicy, SlaTracking, SlaTrackingStatus

from .models import (
    FeeVerificationStatus,
    SampleFeeDecision,
    SampleFeeRecord,
    SampleFeedback,
    SampleFileLink,
    SampleItem,
    SampleRequest,
    SampleRequestStatus,
    SampleShipment,
    SampleShipmentItem,
    SampleShipmentStatus,
    SampleSlaLink,
)


SAMPLE_FIELDS = [
    "customer_account",
    "transaction_entity",
    "customer_contact",
    "owner_employee",
    "source_inquiry",
    "source_quotation_version",
    "request_number",
    "status",
    "purpose",
    "requested_at",
    "requested_due_at",
    "notes",
]
ITEM_FIELDS = [
    "sample_request",
    "line_number",
    "product_description_snapshot",
    "specification_snapshot",
    "requested_quantity",
    "unit_code",
    "notes",
]


def _touch(instance):
    instance.updated_at = timezone.now()
    instance.save(update_fields=["updated_at"])


def _write_sample_records(*, sample_request, action, actor_employee, request, before_data=None, note=""):
    write_audit_log(
        object_type="SAMPLE_REQUEST",
        object_id=sample_request.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action=action,
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={**model_snapshot(sample_request, SAMPLE_FIELDS), "note": note},
        request=request,
    )
    write_customer_timeline(
        customer=sample_request.customer_account,
        event_type=f"SAMPLE_{action}",
        title=f"{sample_request.request_number} 样品申请",
        summary=note,
        source_type="SAMPLE_REQUEST",
        source_id=sample_request.pk,
        actor_employee=actor_employee,
    )


def _assigned_line_number(item_data, used, fallback):
    requested = item_data.pop("line_number", None)
    if requested is not None:
        used.add(requested)
        return requested
    candidate = fallback
    while candidate in used:
        candidate += 1
    used.add(candidate)
    return candidate


@transaction.atomic
def create_sample_request(*, validated_data, actor_employee, request):
    items = validated_data.pop("items", [])
    sample_request = SampleRequest.objects.create(
        request_number=next_business_number("SAMPLE"),
        status=SampleRequestStatus.DRAFT,
        **validated_data,
    )
    used = {item["line_number"] for item in items if "line_number" in item}
    SampleItem.objects.bulk_create(
        [
            SampleItem(
                sample_request=sample_request,
                line_number=_assigned_line_number(item, used, index),
                **item,
            )
            for index, item in enumerate([dict(item) for item in items], start=1)
        ]
    )
    _write_sample_records(
        sample_request=sample_request,
        action="CREATED",
        actor_employee=actor_employee,
        request=request,
        note=f"同时创建 {len(items)} 条样品明细。",
    )
    return sample_request


@transaction.atomic
def update_sample_request(*, sample_request, validated_data, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status != SampleRequestStatus.DRAFT:
        raise Conflict("只有草稿样品申请可以修改。")
    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    for field_name, value in validated_data.items():
        setattr(sample_request, field_name, value)
    sample_request.save(update_fields=[*validated_data.keys(), "updated_at"])
    _write_sample_records(
        sample_request=sample_request,
        action="UPDATED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
    )
    return sample_request


def _ensure_draft(sample_request):
    if sample_request.status != SampleRequestStatus.DRAFT:
        raise Conflict("样品申请提交后明细只读。")


@transaction.atomic
def create_sample_item(*, sample_request, validated_data, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    _ensure_draft(sample_request)
    if sample_request.items.count() >= 200:
        raise ValidationError({"detail": "单张样品申请最多包含 200 条明细。"})
    data = dict(validated_data)
    if "line_number" not in data:
        data["line_number"] = (sample_request.items.aggregate(value=Max("line_number"))["value"] or 0) + 1
    item = SampleItem.objects.create(sample_request=sample_request, **data)
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_ITEM",
        object_id=item.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=model_snapshot(item, ITEM_FIELDS),
        request=request,
    )
    return item, sample_request


@transaction.atomic
def update_sample_item(*, item, validated_data, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=item.sample_request_id)
    require_matching_etag(request, sample_request)
    _ensure_draft(sample_request)
    item = SampleItem.objects.select_for_update().get(pk=item.pk)
    before_data = model_snapshot(item, ITEM_FIELDS)
    for field_name, value in validated_data.items():
        setattr(item, field_name, value)
    item.save(update_fields=[*validated_data.keys(), "updated_at"])
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_ITEM",
        object_id=item.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(item, ITEM_FIELDS),
        request=request,
    )
    return item, sample_request


@transaction.atomic
def delete_sample_item(*, item, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=item.sample_request_id)
    require_matching_etag(request, sample_request)
    _ensure_draft(sample_request)
    item = SampleItem.objects.select_for_update().get(pk=item.pk)
    before_data = model_snapshot(item, ITEM_FIELDS)
    item_id = item.pk
    item.delete()
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_ITEM",
        object_id=item_id,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="DELETED",
        actor_employee=actor_employee,
        before_data=before_data,
        request=request,
    )
    return sample_request


def _start_sla(sample_request, started_at):
    policy = SlaPolicy.objects.filter(
        target_type="SAMPLE_REQUEST",
        is_enabled=True,
        archived_at__isnull=True,
    ).order_by("policy_code").first()
    if policy is None:
        return
    minutes = policy.resolution_minutes or policy.response_minutes
    tracking = SlaTracking.objects.create(
        sla_policy=policy,
        status=SlaTrackingStatus.RUNNING,
        started_at=started_at,
        next_deadline_at=started_at + timedelta(minutes=minutes) if minutes else None,
        tracking_data={
            "target_kind": "RESOLUTION" if policy.resolution_minutes else "RESPONSE",
            "target_minutes": minutes,
        },
    )
    SampleSlaLink.objects.create(sample_request=sample_request, sla_tracking=tracking)


def _finish_sla(sample_request, cancelled, finished_at):
    for link in SampleSlaLink.objects.select_related("sla_tracking").filter(sample_request=sample_request):
        tracking = link.sla_tracking
        if tracking.status != SlaTrackingStatus.RUNNING:
            continue
        if cancelled:
            tracking.status = SlaTrackingStatus.CANCELLED
        elif tracking.next_deadline_at and finished_at > tracking.next_deadline_at:
            tracking.status = SlaTrackingStatus.BREACHED
            tracking.breached_at = finished_at
        else:
            tracking.status = SlaTrackingStatus.MET
        tracking.completed_at = finished_at
        tracking.save(update_fields=["status", "breached_at", "completed_at", "updated_at"])


@transaction.atomic
def transition_sample_request(*, sample_request, action, note, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    transitions = {
        "SUBMITTED": ({SampleRequestStatus.DRAFT}, SampleRequestStatus.PENDING),
        "PREPARING_STARTED": ({SampleRequestStatus.PENDING}, SampleRequestStatus.PREPARING),
        "COMPLETED": ({SampleRequestStatus.FEEDBACK_PENDING}, SampleRequestStatus.COMPLETED),
        "CANCELLED": (
            {SampleRequestStatus.DRAFT, SampleRequestStatus.PENDING, SampleRequestStatus.PREPARING},
            SampleRequestStatus.CANCELLED,
        ),
    }
    allowed, target = transitions[action]
    if sample_request.status not in allowed:
        raise Conflict(f"当前样品申请状态 {sample_request.status} 不允许执行此动作。")
    if action == "SUBMITTED" and not sample_request.items.exists():
        raise Conflict("样品申请至少包含一条明细后才能提交。")
    if action == "COMPLETED" and not sample_request.feedback_records.exists():
        raise Conflict("至少记录一条客户反馈后才能完成样品申请。")
    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    now = timezone.now()
    sample_request.status = target
    sample_request.save(update_fields=["status", "updated_at"])
    if action == "SUBMITTED":
        _start_sla(sample_request, now)
    elif action == "COMPLETED":
        _finish_sla(sample_request, False, now)
    elif action == "CANCELLED":
        _finish_sla(sample_request, True, now)
    _write_sample_records(
        sample_request=sample_request,
        action=action,
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note,
    )
    return sample_request


@transaction.atomic
def create_fee_record(*, sample_request, validated_data, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status not in {SampleRequestStatus.PENDING, SampleRequestStatus.PREPARING}:
        raise Conflict("只有待处理或准备中的样品申请可以新增收费决策。")
    if (
        validated_data["verification_status"] == FeeVerificationStatus.EVIDENCE_UPLOADED
        and not sample_request.file_links.filter(file_role="FEE_EVIDENCE").exists()
    ):
        raise Conflict("标记为已上传凭证前，必须先关联 FEE_EVIDENCE 文件。")
    now = timezone.now()
    sample_request.fee_records.filter(superseded_at__isnull=True).update(superseded_at=now, updated_at=now)
    record = SampleFeeRecord.objects.create(
        sample_request=sample_request,
        decided_by_employee=actor_employee,
        decided_at=now,
        **validated_data,
    )
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_FEE_RECORD",
        object_id=record.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="DECIDED",
        actor_employee=actor_employee,
        after_data={
            "sample_request_id": str(sample_request.pk),
            "fee_decision": record.fee_decision,
            "amount": str(record.amount),
            "currency_code": record.currency_code,
            "verification_status": record.verification_status,
            "decision_reason": record.decision_reason,
        },
        request=request,
    )
    write_customer_timeline(
        customer=sample_request.customer_account,
        event_type="SAMPLE_FEE_DECIDED",
        title=f"{sample_request.request_number} 费用：{record.get_fee_decision_display()}",
        summary=record.decision_reason,
        source_type="SAMPLE_FEE_RECORD",
        source_id=record.pk,
        actor_employee=actor_employee,
    )
    return record, sample_request


@transaction.atomic
def create_shipment(*, sample_request, items, actor_employee, request, notes=""):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status not in {SampleRequestStatus.PREPARING, SampleRequestStatus.SHIPPED}:
        raise Conflict("只有准备中或已有寄送在途的申请可以新增寄送记录。")
    shipment = SampleShipment.objects.create(sample_request=sample_request, notes=notes)
    SampleShipmentItem.objects.bulk_create(
        [
            SampleShipmentItem(
                sample_shipment=shipment,
                sample_item=item["sample_item"],
                shipped_quantity=item["shipped_quantity"],
            )
            for item in items
        ]
    )
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_SHIPMENT",
        object_id=shipment.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={
            "sample_request_id": str(sample_request.pk),
            "item_ids": [str(item["sample_item"].pk) for item in items],
        },
        request=request,
    )
    return shipment, sample_request


def _contact_snapshot(contact):
    return {
        "id": str(contact.pk),
        "display_name": contact.display_name,
        "position_title": contact.position_title,
        "methods": [
            {"method_type": method.method_type, "value": method.raw_value}
            for method in contact.methods.filter(archived_at__isnull=True).order_by("method_type", "id")
        ],
    }


def _address_snapshot(address):
    return {
        "id": str(address.pk),
        "address_code": address.address_code,
        "country_code": address.country_code,
        "state_province": address.state_province,
        "city": address.city,
        "postal_code": address.postal_code,
        "address_line1": address.address_line1,
        "address_line2": address.address_line2,
        "recipient_name": address.recipient_name,
        "recipient_phone": address.recipient_phone,
    }


@transaction.atomic
def ship_sample(*, shipment, validated_data, actor_employee, request):
    shipment = SampleShipment.objects.select_for_update().get(pk=shipment.pk)
    require_matching_etag(request, shipment)
    sample_request = SampleRequest.objects.select_for_update().get(pk=shipment.sample_request_id)
    if shipment.status != SampleShipmentStatus.PREPARING:
        raise Conflict("只有准备中的寄送记录可以寄出。")
    if sample_request.status not in {SampleRequestStatus.PREPARING, SampleRequestStatus.SHIPPED}:
        raise Conflict("当前样品申请状态不允许寄出。")
    if not shipment.items.exists():
        raise Conflict("寄送记录至少包含一条寄送明细。")
    fee = sample_request.fee_records.filter(superseded_at__isnull=True).first()
    if fee is None or fee.fee_decision == SampleFeeDecision.PENDING:
        raise Conflict("寄出前必须完成样品收费决策。")
    warning_required = (
        fee.fee_decision == SampleFeeDecision.PAID
        and fee.verification_status != FeeVerificationStatus.MANUALLY_CONFIRMED
    )
    acknowledged = validated_data["fee_warning_acknowledged"]
    if warning_required and not acknowledged:
        raise Conflict("收费尚未人工确认，寄出前必须显式确认风险并填写原因。")
    now = timezone.now()
    contact = validated_data["contact"]
    address = validated_data["address"]
    reason = validated_data.get("fee_warning_reason", "").strip()
    action_notes = validated_data.get("notes", "").strip()
    note_parts = [shipment.notes, action_notes]
    if acknowledged:
        note_parts.append(f"收费风险确认：{reason}")
    shipment.status = SampleShipmentStatus.SHIPPED
    shipment.carrier_code = validated_data["carrier_code"]
    shipment.tracking_number = validated_data["tracking_number"]
    shipment.recipient_snapshot = _contact_snapshot(contact)
    shipment.address_snapshot = _address_snapshot(address)
    shipment.shipped_by_employee = actor_employee
    shipment.shipped_at = now
    shipment.fee_warning_acknowledged = acknowledged
    shipment.fee_warning_acknowledged_by_employee = actor_employee if acknowledged else None
    shipment.fee_warning_acknowledged_at = now if acknowledged else None
    shipment.notes = "\n".join(part for part in note_parts if part)
    shipment.save(
        update_fields=[
            "status",
            "carrier_code",
            "tracking_number",
            "recipient_snapshot",
            "address_snapshot",
            "shipped_by_employee",
            "shipped_at",
            "fee_warning_acknowledged",
            "fee_warning_acknowledged_by_employee",
            "fee_warning_acknowledged_at",
            "notes",
            "updated_at",
        ]
    )
    if sample_request.status == SampleRequestStatus.PREPARING:
        sample_request.status = SampleRequestStatus.SHIPPED
        sample_request.save(update_fields=["status", "updated_at"])
    else:
        _touch(sample_request)
    _write_sample_records(
        sample_request=sample_request,
        action="SHIPPED",
        actor_employee=actor_employee,
        request=request,
        note=f"{shipment.carrier_code} {shipment.tracking_number}",
    )
    return shipment, sample_request


@transaction.atomic
def deliver_sample(*, shipment, note, actor_employee, request):
    shipment = SampleShipment.objects.select_for_update().get(pk=shipment.pk)
    require_matching_etag(request, shipment)
    sample_request = SampleRequest.objects.select_for_update().get(pk=shipment.sample_request_id)
    if shipment.status != SampleShipmentStatus.SHIPPED:
        raise Conflict("只有已寄出的记录可以标记送达。")
    now = timezone.now()
    shipment.status = SampleShipmentStatus.DELIVERED
    shipment.delivered_at = now
    if note:
        shipment.notes = "\n".join(part for part in [shipment.notes, note] if part)
    shipment.save(update_fields=["status", "delivered_at", "notes", "updated_at"])
    has_open_shipments = sample_request.shipments.exclude(
        status__in=[SampleShipmentStatus.DELIVERED, SampleShipmentStatus.CANCELLED]
    ).exists()
    if not has_open_shipments and sample_request.status == SampleRequestStatus.SHIPPED:
        sample_request.status = SampleRequestStatus.FEEDBACK_PENDING
        sample_request.save(update_fields=["status", "updated_at"])
    else:
        _touch(sample_request)
    _write_sample_records(
        sample_request=sample_request,
        action="DELIVERED",
        actor_employee=actor_employee,
        request=request,
        note=note,
    )
    return shipment, sample_request


@transaction.atomic
def create_feedback(*, sample_request, validated_data, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status not in {SampleRequestStatus.FEEDBACK_PENDING, SampleRequestStatus.COMPLETED}:
        raise Conflict("只有待反馈或已完成的样品申请可以记录反馈。")
    feedback = SampleFeedback.objects.create(
        sample_request=sample_request,
        recorded_by_employee=actor_employee,
        **validated_data,
    )
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_FEEDBACK",
        object_id=feedback.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={
            "sample_request_id": str(sample_request.pk),
            "feedback_type": feedback.feedback_type,
            "feedback_content": feedback.feedback_content,
            "occurred_at": feedback.occurred_at,
        },
        request=request,
    )
    write_customer_timeline(
        customer=sample_request.customer_account,
        event_type="SAMPLE_FEEDBACK_CREATED",
        title=f"{sample_request.request_number} 收到样品反馈",
        summary=feedback.feedback_content[:500],
        source_type="SAMPLE_FEEDBACK",
        source_id=feedback.pk,
        actor_employee=actor_employee,
        occurred_at=feedback.occurred_at,
    )
    return feedback, sample_request


@transaction.atomic
def link_sample_file(*, sample_request, business_file, file_role, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status in {SampleRequestStatus.COMPLETED, SampleRequestStatus.CANCELLED}:
        raise Conflict("终态样品申请不能再关联文件。")
    link = SampleFileLink.objects.create(
        sample_request=sample_request,
        business_file=business_file,
        file_role=file_role,
    )
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_FILE_LINK",
        object_id=link.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={
            "sample_request_id": str(sample_request.pk),
            "business_file_id": str(business_file.pk),
            "file_role": file_role,
        },
        request=request,
    )
    return link, sample_request
