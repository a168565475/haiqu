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

from .models import Inquiry, InquiryFileLink, InquiryItem, InquirySlaLink, InquiryStatus


INQUIRY_FIELDS = [
    "customer_account",
    "transaction_entity",
    "customer_contact",
    "owner_employee",
    "inquiry_number",
    "status",
    "inquiry_source",
    "subject",
    "description",
    "received_at",
    "requested_due_at",
    "submitted_at",
    "source_system",
    "external_id",
]
ITEM_FIELDS = [
    "inquiry",
    "line_number",
    "product_description",
    "specification",
    "quantity",
    "unit_code",
    "target_unit_price",
    "target_currency_code",
    "notes",
]


def _touch_inquiry(inquiry):
    inquiry.updated_at = timezone.now()
    inquiry.save(update_fields=["updated_at"])


def _write_inquiry_records(*, inquiry, action, actor_employee, request, before_data=None, note=""):
    write_audit_log(
        object_type="INQUIRY",
        object_id=inquiry.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action=action,
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={**model_snapshot(inquiry, INQUIRY_FIELDS), "note": note},
        request=request,
    )
    write_customer_timeline(
        customer=inquiry.customer_account,
        event_type=f"INQUIRY_{action}",
        title=f"{inquiry.inquiry_number} {inquiry.subject}",
        summary=note,
        source_type="INQUIRY",
        source_id=inquiry.pk,
        actor_employee=actor_employee,
    )


def _line_number(item_data, used_numbers, fallback):
    requested = item_data.pop("line_number", None)
    if requested is not None:
        used_numbers.add(requested)
        return requested
    candidate = fallback
    while candidate in used_numbers:
        candidate += 1
    used_numbers.add(candidate)
    return candidate


@transaction.atomic
def create_inquiry(*, validated_data, actor_employee, request):
    items = validated_data.pop("items", [])
    inquiry = Inquiry.objects.create(
        inquiry_number=next_business_number("INQUIRY"),
        status=InquiryStatus.DRAFT,
        **validated_data,
    )
    used_numbers = {item["line_number"] for item in items if "line_number" in item}
    created_items = []
    for index, item_data in enumerate(items, start=1):
        item_data = dict(item_data)
        created_items.append(
            InquiryItem(
                inquiry=inquiry,
                line_number=_line_number(item_data, used_numbers, index),
                **item_data,
            )
        )
    InquiryItem.objects.bulk_create(created_items)
    _write_inquiry_records(
        inquiry=inquiry,
        action="CREATED",
        actor_employee=actor_employee,
        request=request,
        note=f"同时创建 {len(created_items)} 条询价明细。",
    )
    return inquiry


@transaction.atomic
def update_inquiry(*, inquiry, validated_data, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    if inquiry.status != InquiryStatus.DRAFT:
        raise Conflict("只有草稿询价可以修改。")
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    for field_name, value in validated_data.items():
        setattr(inquiry, field_name, value)
    inquiry.save(update_fields=[*validated_data.keys(), "updated_at"])
    _write_inquiry_records(
        inquiry=inquiry,
        action="UPDATED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
    )
    return inquiry


def _ensure_draft(inquiry):
    if inquiry.status != InquiryStatus.DRAFT:
        raise Conflict("询价提交后明细只读；如需更正，请取消原询价并新建询价。")


@transaction.atomic
def create_inquiry_item(*, inquiry, validated_data, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    _ensure_draft(inquiry)
    if inquiry.items.count() >= 200:
        raise ValidationError({"detail": "单张询价最多包含 200 条明细。"})
    item_data = dict(validated_data)
    if "line_number" not in item_data:
        current_max = inquiry.items.aggregate(value=Max("line_number"))["value"] or 0
        item_data["line_number"] = current_max + 1
    item = InquiryItem.objects.create(inquiry=inquiry, **item_data)
    _touch_inquiry(inquiry)
    write_audit_log(
        object_type="INQUIRY_ITEM",
        object_id=item.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=model_snapshot(item, ITEM_FIELDS),
        request=request,
    )
    write_customer_timeline(
        customer=inquiry.customer_account,
        event_type="INQUIRY_ITEM_CREATED",
        title=f"{inquiry.inquiry_number} 新增明细第 {item.line_number} 行",
        source_type="INQUIRY",
        source_id=inquiry.pk,
        actor_employee=actor_employee,
    )
    return item, inquiry


@transaction.atomic
def update_inquiry_item(*, item, validated_data, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=item.inquiry_id)
    require_matching_etag(request, inquiry)
    _ensure_draft(inquiry)
    item = InquiryItem.objects.select_for_update().get(pk=item.pk)
    before_data = model_snapshot(item, ITEM_FIELDS)
    for field_name, value in validated_data.items():
        setattr(item, field_name, value)
    item.save(update_fields=[*validated_data.keys(), "updated_at"])
    _touch_inquiry(inquiry)
    write_audit_log(
        object_type="INQUIRY_ITEM",
        object_id=item.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(item, ITEM_FIELDS),
        request=request,
    )
    return item, inquiry


@transaction.atomic
def delete_inquiry_item(*, item, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=item.inquiry_id)
    require_matching_etag(request, inquiry)
    _ensure_draft(inquiry)
    item = InquiryItem.objects.select_for_update().get(pk=item.pk)
    before_data = model_snapshot(item, ITEM_FIELDS)
    item_id = item.pk
    item.delete()
    _touch_inquiry(inquiry)
    write_audit_log(
        object_type="INQUIRY_ITEM",
        object_id=item_id,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action="DELETED",
        actor_employee=actor_employee,
        before_data=before_data,
        request=request,
    )
    return inquiry


def _start_sla(inquiry, started_at):
    policy = SlaPolicy.objects.filter(
        target_type="INQUIRY",
        is_enabled=True,
        archived_at__isnull=True,
    ).order_by("policy_code").first()
    if policy is None:
        return
    target_minutes = policy.resolution_minutes or policy.response_minutes
    deadline = started_at + timedelta(minutes=target_minutes) if target_minutes else None
    tracking = SlaTracking.objects.create(
        sla_policy=policy,
        status=SlaTrackingStatus.RUNNING,
        started_at=started_at,
        next_deadline_at=deadline,
        tracking_data={
            "target_kind": "RESOLUTION" if policy.resolution_minutes else "RESPONSE",
            "target_minutes": target_minutes,
        },
    )
    InquirySlaLink.objects.create(inquiry=inquiry, sla_tracking=tracking)


def _finish_sla(inquiry, target_status, finished_at):
    for link in InquirySlaLink.objects.select_related("sla_tracking").filter(inquiry=inquiry):
        tracking = link.sla_tracking
        if tracking.status != SlaTrackingStatus.RUNNING:
            continue
        if target_status == SlaTrackingStatus.CANCELLED:
            tracking.status = SlaTrackingStatus.CANCELLED
        elif tracking.next_deadline_at and finished_at > tracking.next_deadline_at:
            tracking.status = SlaTrackingStatus.BREACHED
            tracking.breached_at = finished_at
        else:
            tracking.status = SlaTrackingStatus.MET
        tracking.completed_at = finished_at
        tracking.save(update_fields=["status", "breached_at", "completed_at", "updated_at"])


@transaction.atomic
def transition_inquiry(*, inquiry, action, note, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    transitions = {
        "SUBMITTED": ({InquiryStatus.DRAFT}, InquiryStatus.SUBMITTED),
        "STARTED": ({InquiryStatus.SUBMITTED}, InquiryStatus.IN_PROGRESS),
        "MARKED_QUOTED": ({InquiryStatus.IN_PROGRESS}, InquiryStatus.QUOTED),
        "CLOSED": (
            {InquiryStatus.SUBMITTED, InquiryStatus.IN_PROGRESS, InquiryStatus.QUOTED},
            InquiryStatus.CLOSED,
        ),
        "CANCELLED": (
            {InquiryStatus.DRAFT, InquiryStatus.SUBMITTED, InquiryStatus.IN_PROGRESS, InquiryStatus.QUOTED},
            InquiryStatus.CANCELLED,
        ),
    }
    allowed_statuses, target_status = transitions[action]
    if inquiry.status not in allowed_statuses:
        raise Conflict(f"当前询价状态 {inquiry.status} 不允许执行此动作。")
    if action == "SUBMITTED" and not inquiry.items.exists():
        raise Conflict("询价至少包含一条明细后才能提交。")
    now = timezone.now()
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    inquiry.status = target_status
    update_fields = ["status", "updated_at"]
    if action == "SUBMITTED":
        inquiry.submitted_at = now
        update_fields.append("submitted_at")
    inquiry.save(update_fields=update_fields)
    if action == "SUBMITTED":
        _start_sla(inquiry, now)
    elif action in {"MARKED_QUOTED", "CLOSED"}:
        _finish_sla(inquiry, SlaTrackingStatus.MET, now)
    elif action == "CANCELLED":
        _finish_sla(inquiry, SlaTrackingStatus.CANCELLED, now)
    _write_inquiry_records(
        inquiry=inquiry,
        action=action,
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note,
    )
    return inquiry


@transaction.atomic
def link_inquiry_file(*, inquiry, business_file, file_role, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    if inquiry.status in {InquiryStatus.CLOSED, InquiryStatus.CANCELLED}:
        raise Conflict("终态询价不能再关联文件。")
    link = InquiryFileLink.objects.create(
        inquiry=inquiry,
        business_file=business_file,
        file_role=file_role,
    )
    _touch_inquiry(inquiry)
    write_audit_log(
        object_type="INQUIRY_FILE_LINK",
        object_id=link.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={
            "inquiry_id": str(inquiry.pk),
            "business_file_id": str(business_file.pk),
            "file_role": file_role,
        },
        request=request,
    )
    return link, inquiry
