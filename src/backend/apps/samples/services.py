from apps.access_control import sales_policy
from datetime import datetime, time, timedelta

from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.customers.services import model_snapshot, write_customer_timeline
from apps.customers.models import CustomerContact
from apps.inquiries.models import Inquiry, InquiryStatus
from apps.quotations.models import QuotationOutcomeStatus, QuotationVersion, QuotationVersionStatus
from apps.quotations.services import create_requotation_draft
from apps.workflow.models import ApprovalRequest, ApprovalStatus, SlaPolicy, SlaTracking, SlaTrackingStatus
from apps.workflow.models import BusinessTask, TaskOriginType, TaskPriority, TaskStatus, TaskType
from apps.workflow.services import create_task, transition_task

from .models import (
    FeeVerificationStatus,
    FeeApprovalStatus,
    SampleFeeDecision,
    SampleFeeRecord,
    SampleFeedback,
    FeedbackConfirmationResult,
    SampleFileLink,
    SampleParameterImage,
    SampleItem,
    SampleProduct,
    SampleRequest,
    SampleRequestStatus,
    SampleWorkflowRecord,
    SampleWorkflowStage,
    SampleType,
    SampleShipment,
    SampleShipmentEvent,
    SampleShipmentItem,
    ShipmentEventSource,
    ShipmentEventType,
    SampleShipmentStatus,
    SampleSlaLink,
    SampleApprovalLink,
    SampleTaskLink,
)


SAMPLE_FIELDS = [
    "customer_account",
    "transaction_entity",
    "customer_contact",
    "owner_employee",
    "source_inquiry",
    "source_quotation_version",
    "request_number",
    "intake_number",
    "manual_request_number",
    "requested_by_employee",
    "created_by_employee",
    "shipping_method",
    "order_date",
    "sample_due_date",
    "delivery_batch",
    "is_repeat_order",
    "submitted_on",
    "creation_idempotency_key",
    "application_payload_hash",
    "reference_image",
    "director_note",
    "status",
    "sample_type",
    "purpose",
    "requested_at",
    "requested_due_at",
    "expected_shipped_at",
    "expected_received_at",
    "notes",
]
ITEM_FIELDS = [
    "sample_request",
    "line_number",
    "source_inquiry_item",
    "source_quotation_line",
    "product_description_snapshot",
    "specification_snapshot",
    "requested_quantity",
    "unit_code",
    "notes",
]


def sample_product_values_from_source(source):
    """复制询盘或报价的产品快照，样品仍保持自己的可编辑记录。"""
    product = getattr(source, "product", None)
    if product is None and hasattr(source, "product_number") and hasattr(source, "product_item"):
        product = source
    source_name = (
        getattr(source, "product_description", "")
        or getattr(source, "product_description_snapshot", "")
        or getattr(product, "product_name", "")
    )
    source_specification = (
        getattr(source, "specification", "")
        or getattr(source, "specification_snapshot", "")
        or getattr(product, "specification", "")
    )
    if product is not None:
        product_number = product.product_number
        product_code = product.product_code
        item_number = product.product_item.item_number
    else:
        product_number = getattr(source, "product_number_snapshot", "")
        product_code = getattr(source, "product_code_snapshot", "")
        item_number = getattr(source, "item_number_snapshot", "")
    return {
        "product": product,
        "product_number_snapshot": product_number,
        "product_code_snapshot": product_code,
        "item_number_snapshot": item_number,
        "product_name": source_name,
        "specification": source_specification,
        "material_snapshot": getattr(source, "material", "") or getattr(source, "material_snapshot", ""),
        "product_image": getattr(source, "product_image", None),
    }


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


def _record_workflow_stage(
    *,
    sample_request,
    stage,
    actor_employee,
    note="",
    business_file=None,
    operated_at=None,
):
    """写入一条不可重复的主流程节点记录。"""

    record, created = SampleWorkflowRecord.objects.get_or_create(
        sample_request=sample_request,
        stage=stage,
        defaults={
            "business_file": business_file,
            "note": note.strip(),
            "operated_by_employee": actor_employee,
            "operated_at": operated_at or timezone.now(),
        },
    )
    if not created:
        raise Conflict("该流程步骤已经处理，请刷新页面查看最新状态。")
    return record


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
    collaborators = validated_data.pop("collaborators", [])
    sample_request = SampleRequest.objects.create(
        request_number=next_business_number("SAMPLE"),
        requested_by_employee=actor_employee,
        created_by_employee=actor_employee,
        status=SampleRequestStatus.DRAFT,
        **validated_data,
    )
    from apps.access_control.module_policy import require_sample_reporting_changes
    require_sample_reporting_changes(request, sample_request, items)
    if collaborators:
        sample_request.collaborators.set(collaborators)
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
    _record_workflow_stage(
        sample_request=sample_request,
        stage=SampleWorkflowStage.REQUEST_CREATED,
        actor_employee=actor_employee,
        note="创建样品需求。",
        operated_at=sample_request.created_at,
    )
    return sample_request


def _replayed_source_sample(*, idempotency_key, source_inquiry_id=None, source_quotation_version_id=None):
    existing = SampleRequest.objects.filter(creation_idempotency_key=idempotency_key).first()
    if existing is None:
        return None
    if (
        existing.source_inquiry_id != source_inquiry_id
        or existing.source_quotation_version_id != source_quotation_version_id
    ):
        raise Conflict("幂等键已被其他来源的样品申请使用，请刷新后重试。")
    return existing


def _source_due_datetime(date_value):
    if date_value is None:
        return None
    return timezone.make_aware(
        datetime.combine(date_value, time.min),
        timezone.get_current_timezone(),
    )


def _create_intake_products(*, sample_request, selections, source_type):
    for line_number, selection in enumerate(selections, start=1):
        source = selection["source_item"] if source_type == "inquiry" else selection["source_line"]
        quantity = selection["requested_quantity"]
        if source_type == "inquiry":
            product_name = source.product_description
            specification = source.specification
            inquiry_item = source
            quotation_line = None
        else:
            product_name = source.product_description_snapshot
            specification = source.specification_snapshot
            inquiry_item = source.source_inquiry_item
            quotation_line = source
        product_values = sample_product_values_from_source(source)
        product = SampleProduct.objects.create(
            sample_request=sample_request,
            source_inquiry_item=inquiry_item,
            source_quotation_line=quotation_line,
            line_number=line_number,
            **product_values,
        )
        SampleItem.objects.create(
            sample_request=sample_request,
            sample_product=product,
            source_inquiry_item=inquiry_item,
            source_quotation_line=quotation_line,
            line_number=line_number,
            product_description_snapshot=product_name,
            specification_snapshot=specification,
            requested_quantity=quantity,
            unit_code="PCS",
            sample_quantity=quantity,
        )


@transaction.atomic
def create_sample_from_inquiry(*, inquiry_id, validated_data, actor_employee, request):
    """从询盘创建永久 SRQ，并进入待工厂完善队列。"""
    inquiry = Inquiry.objects.select_for_update(of=("self",)).select_related(
        "customer_account",
        "transaction_entity",
        "customer_contact",
        "owner_employee",
    ).prefetch_related("items").get(pk=inquiry_id, archived_at__isnull=True)
    from apps.access_control import module_policy
    if module_policy.enabled():
        sales_policy.require_customer(request, 'inquiries.view_inquiry', inquiry.customer_account)
    idempotency_key = validated_data.pop("idempotency_key")
    replayed = _replayed_source_sample(
        idempotency_key=idempotency_key,
        source_inquiry_id=inquiry.pk,
    )
    if replayed is not None:
        return replayed, True
    if inquiry.status in {
        InquiryStatus.DRAFT,
        InquiryStatus.LOST,
        InquiryStatus.CLOSED,
        InquiryStatus.CANCELLED,
    }:
        raise Conflict("当前询盘状态不能创建样品需求。")
    if inquiry.owner_employee_id is None:
        raise Conflict("询盘尚未分配业务员，请先完成询盘分配再创建样品。")
    selections = validated_data.pop("items")
    if not inquiry.items.exists():
        raise Conflict("询盘没有产品，不能创建样品需求。")
    available_items = {item.pk: item for item in inquiry.items.all()}
    for selection in selections:
        source_item = selection["source_item"]
        if source_item.pk not in available_items:
            raise ValidationError({"items": "所选询价明细不属于当前询盘。"})
    intake_number = next_business_number("SAMPLE_INTAKE")
    due_date = validated_data.pop("sample_due_date", None)
    now = timezone.now()
    sample_request = SampleRequest.objects.create(
        request_number=intake_number,
        intake_number=intake_number,
        customer_account=inquiry.customer_account,
        transaction_entity=inquiry.transaction_entity,
        customer_contact=inquiry.customer_contact,
        owner_employee=inquiry.owner_employee,
        source_inquiry=inquiry,
        requested_by_employee=actor_employee,
        created_by_employee=None,
        creation_idempotency_key=idempotency_key,
        status=SampleRequestStatus.PENDING_COMPLETION,
        sample_due_date=due_date,
        requested_at=now,
        requested_due_at=_source_due_datetime(due_date),
        notes="",
        **validated_data,
    )
    _create_intake_products(sample_request=sample_request, selections=selections, source_type="inquiry")
    _write_sample_records(
        sample_request=sample_request,
        action="INTAKE_CREATED",
        actor_employee=actor_employee,
        request=request,
        note=f"业务员提交 {len(selections)} 个产品，等待工厂完善。",
    )
    _record_workflow_stage(
        sample_request=sample_request,
        stage=SampleWorkflowStage.REQUEST_CREATED,
        actor_employee=actor_employee,
        note="从询盘创建样品需求。",
        operated_at=sample_request.created_at,
    )
    from apps.inquiries.handling_time import sample_submitted
    sample_submitted(sample_request)
    return sample_request, False


@transaction.atomic
def create_sample_from_quotation_version(*, quotation_version_id, validated_data, actor_employee, request):
    """从当前已发送报价版本创建永久 SRQ，并进入待工厂完善队列。"""
    version = QuotationVersion.objects.select_for_update(of=("self",)).select_related(
        "quotation__customer_account",
        "quotation__transaction_entity",
        "quotation__owner_employee",
        "quotation__source_inquiry__customer_contact",
    ).prefetch_related("lines").get(
        pk=quotation_version_id,
        quotation__archived_at__isnull=True,
    )
    quotation = version.quotation
    from apps.access_control import module_policy
    if module_policy.enabled():
        sales_policy.require_customer(request, 'quotations.view_quotationversion', quotation.customer_account)
    latest_version_id = (
        quotation.versions.exclude(status=QuotationVersionStatus.VOID)
        .order_by("-version_number", "-id")
        .values_list("id", flat=True)
        .first()
    )
    if version.status != QuotationVersionStatus.SENT or latest_version_id != version.pk:
        raise Conflict("只能从当前已发送且未作废的报价版本创建样品需求。")
    if quotation.owner_employee_id is None:
        raise Conflict("来源报价尚未分配业务员。")
    idempotency_key = validated_data.pop("idempotency_key")
    replayed = _replayed_source_sample(
        idempotency_key=idempotency_key,
        source_inquiry_id=quotation.source_inquiry_id,
        source_quotation_version_id=version.pk,
    )
    if replayed is not None:
        return replayed, True
    contact = quotation.source_inquiry.customer_contact if quotation.source_inquiry_id else None
    if contact is None and version.contact_snapshot.get("id"):
        contact = CustomerContact.objects.filter(
            pk=version.contact_snapshot["id"],
            customer_account=quotation.customer_account,
            archived_at__isnull=True,
        ).first()
    selections = validated_data.pop("items")
    if not version.lines.exists():
        raise Conflict("报价版本没有产品，不能创建样品需求。")
    available_lines = {line.pk: line for line in version.lines.all()}
    for selection in selections:
        source_line = selection["source_line"]
        if source_line.pk not in available_lines:
            raise ValidationError({"items": "所选报价行不属于当前报价版本。"})
    intake_number = next_business_number("SAMPLE_INTAKE")
    due_date = validated_data.pop("sample_due_date", None)
    now = timezone.now()
    sample_request = SampleRequest.objects.create(
        request_number=intake_number,
        intake_number=intake_number,
        customer_account=quotation.customer_account,
        transaction_entity=quotation.transaction_entity,
        customer_contact=contact,
        owner_employee=quotation.owner_employee,
        source_inquiry=quotation.source_inquiry,
        source_quotation_version=version,
        requested_by_employee=actor_employee,
        created_by_employee=None,
        creation_idempotency_key=idempotency_key,
        status=SampleRequestStatus.PENDING_COMPLETION,
        sample_due_date=due_date,
        requested_at=now,
        requested_due_at=_source_due_datetime(due_date),
        notes="",
        **validated_data,
    )
    _create_intake_products(sample_request=sample_request, selections=selections, source_type="quotation")
    _write_sample_records(
        sample_request=sample_request,
        action="INTAKE_CREATED",
        actor_employee=actor_employee,
        request=request,
        note=f"业务员提交 {len(selections)} 个产品，等待工厂完善。",
    )
    _record_workflow_stage(
        sample_request=sample_request,
        stage=SampleWorkflowStage.REQUEST_CREATED,
        actor_employee=actor_employee,
        note="从报价创建样品需求。",
        operated_at=sample_request.created_at,
    )
    from apps.inquiries.handling_time import sample_submitted
    sample_submitted(sample_request)
    return sample_request, False


def _require_batch_etag(sample_request, etags):
    expected_etag = etags.get(str(sample_request.pk))
    if not expected_etag:
        raise PreconditionRequired("批量操作必须为每条样品记录提供 ETag。")
    if expected_etag != etag_for_instance(sample_request):
        raise PreconditionFailed("部分样品已被其他人修改，请刷新列表后重试。")


@transaction.atomic
def bulk_transfer_sample_requests(*, sample_ids, etags, owner_employee, note, actor_employee, request):
    sample_requests = list(
        SampleRequest.objects.select_for_update()
        .filter(pk__in=sample_ids)
        .select_related("customer_account", "owner_employee")
        .order_by("id")
    )
    if len(sample_requests) != len(set(sample_ids)):
        raise ValidationError({"sample_ids": "部分样品不存在、已归档或无权修改。"})

    updated = []
    for sample_request in sample_requests:
        _require_batch_etag(sample_request, etags)
        if sample_request.owner_employee_id == owner_employee.pk:
            continue
        before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
        sample_request.owner_employee = owner_employee
        sample_request.save(update_fields=["owner_employee", "updated_at"])
        _write_sample_records(
            sample_request=sample_request,
            action="OWNER_BATCH_TRANSFERRED",
            actor_employee=actor_employee,
            request=request,
            before_data=before_data,
            note=note,
        )
        updated.append(sample_request)
    return updated


@transaction.atomic
def bulk_remind_sample_requests(*, sample_ids, etags, note, actor_employee, request):
    sample_requests = list(
        SampleRequest.objects.select_for_update()
        .filter(pk__in=sample_ids)
        .select_related("customer_account", "owner_employee")
        .order_by("id")
    )
    if len(sample_requests) != len(set(sample_ids)):
        raise ValidationError({"sample_ids": "部分样品不存在、已归档或无权访问。"})

    task_ids = []
    today = timezone.localdate().isoformat()
    for sample_request in sample_requests:
        _require_batch_etag(sample_request, etags)
        automation_key = f"SAMPLE_REMIND:{sample_request.pk}:{today}"
        existing_task = BusinessTask.objects.filter(automation_key=automation_key).only("id").first()
        if existing_task:
            task_ids.append(existing_task.pk)
            continue
        task = create_task(
            validated_data={
                "assignee_employee": sample_request.owner_employee,
                "title": f"跟进样品 {sample_request.request_number}",
                "description": note or "请跟进样品当前进度。",
                "priority": TaskPriority.NORMAL,
                "due_at": timezone.now(),
                "automation_key": automation_key,
                "source_type": "SAMPLE_REQUEST",
                "source_id": str(sample_request.pk),
            },
            actor_employee=actor_employee,
            request=request,
            resolved_source=(sample_request, sample_request.customer_account, SampleTaskLink, "sample_request"),
        )
        _write_sample_records(
            sample_request=sample_request,
            action="REMINDER_CREATED",
            actor_employee=actor_employee,
            request=request,
            note=note,
        )
        task_ids.append(task.pk)
    return task_ids


@transaction.atomic
def update_sample_request(*, sample_request, validated_data, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status != SampleRequestStatus.DRAFT:
        raise Conflict("只有草稿样品申请可以修改。")
    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    collaborators = validated_data.pop("collaborators", None)
    for field_name, value in validated_data.items():
        setattr(sample_request, field_name, value)
    if validated_data:
        sample_request.save(update_fields=[*validated_data.keys(), "updated_at"])
    if collaborators is not None:
        sample_request.collaborators.set(collaborators)
        if not validated_data:
            _touch(sample_request)
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
    from apps.access_control.module_policy import require_sample_reporting_changes
    require_sample_reporting_changes(request, sample_request, [data])
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
    from apps.access_control.module_policy import require_sample_reporting_changes
    require_sample_reporting_changes(request, sample_request, [dict(validated_data, id=item.pk)])
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
        "COMPLETED": (
            {SampleRequestStatus.DELIVERED, SampleRequestStatus.FEEDBACK_PENDING},
            SampleRequestStatus.CONFIRMED,
        ),
        "REJECTED": (
            {SampleRequestStatus.DELIVERED, SampleRequestStatus.FEEDBACK_PENDING},
            SampleRequestStatus.REJECTED,
        ),
        "CANCELLED": (
            {
                SampleRequestStatus.DRAFT,
                SampleRequestStatus.PENDING_COMPLETION,
                SampleRequestStatus.PENDING,
                SampleRequestStatus.PMC_REVIEW,
                SampleRequestStatus.METALWORK_PENDING,
                SampleRequestStatus.CUTTING_PENDING,
                SampleRequestStatus.PREPARING,
                SampleRequestStatus.SHIPPED,
                SampleRequestStatus.DELIVERED,
                SampleRequestStatus.FEEDBACK_PENDING,
            },
            SampleRequestStatus.CANCELLED,
        ),
    }
    allowed, target = transitions[action]
    if sample_request.status not in allowed:
        raise Conflict(f"当前样品申请状态 {sample_request.status} 不允许执行此动作。")
    if action == "SUBMITTED" and not sample_request.items.exists():
        raise Conflict("样品申请至少包含一条明细后才能提交。")
    if action == "COMPLETED" and not sample_request.feedback_records.filter(
        confirmation_result=FeedbackConfirmationResult.PASSED
    ).exists():
        raise Conflict("至少记录一条“确认通过”的客户反馈后才能完成样品申请。")
    if action == "REJECTED" and not sample_request.feedback_records.filter(
        confirmation_result=FeedbackConfirmationResult.REJECTED
    ).exists():
        raise Conflict("至少记录一条“确认未通过”的客户反馈后才能标记未通过。")
    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    now = timezone.now()
    sample_request.status = target
    sample_request.save(update_fields=["status", "updated_at"])
    if action == "SUBMITTED":
        _start_sla(sample_request, now)
        from apps.inquiries.handling_time import sample_submitted
        sample_submitted(sample_request)
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
def confirm_sample_finance(*, sample_request, note, business_file, actor_employee, request):
    """财务通过备注或安全凭证完成确认，并把主流程交给 PMC。"""

    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status != SampleRequestStatus.PENDING:
        raise Conflict("只有财务待确认的样品单可以执行财务确认。")
    cleaned_note = note.strip()
    if business_file is None and not cleaned_note:
        raise ValidationError({"note": "请上传财务凭证，或填写人工确认备注。"})

    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    now = timezone.now()
    if business_file is not None:
        SampleFileLink.objects.create(
            sample_request=sample_request,
            business_file=business_file,
            file_role="FINANCE_CONFIRMATION",
        )

    current_fee = SampleFeeRecord.objects.select_for_update().filter(
        sample_request=sample_request,
        superseded_at__isnull=True,
    ).first()
    if current_fee is not None:
        current_fee.verification_status = (
            FeeVerificationStatus.EVIDENCE_UPLOADED
            if business_file is not None
            else FeeVerificationStatus.MANUALLY_CONFIRMED
        )
        current_fee.decided_by_employee = actor_employee
        current_fee.decided_at = now
        current_fee.save(
            update_fields=[
                "verification_status",
                "decided_by_employee",
                "decided_at",
                "updated_at",
            ]
        )

    _record_workflow_stage(
        sample_request=sample_request,
        stage=SampleWorkflowStage.FINANCE_CONFIRMED,
        actor_employee=actor_employee,
        note=cleaned_note,
        business_file=business_file,
        operated_at=now,
    )
    sample_request.status = SampleRequestStatus.PMC_REVIEW
    sample_request.save(update_fields=["status", "updated_at"])
    _write_sample_records(
        sample_request=sample_request,
        action="FINANCE_CONFIRMED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=cleaned_note or "财务已上传凭证并确认。",
    )
    return sample_request


@transaction.atomic
def approve_sample_pmc(*, sample_request, note, actor_employee, request):
    from apps.access_control.module_policy import prohibit_audit_self_approval
    """PMC 审核；审批人不能是本轮实际提交人。"""

    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    prohibit_audit_self_approval(actor_employee, 'SAMPLE_REQUEST', sample_request.pk, ['SUBMITTED', 'CREATED_SUBMITTED', 'REQUIREMENTS_COMPLETED'])
    if sample_request.status != SampleRequestStatus.PMC_REVIEW:
        raise Conflict("只有 PMC 待审核的样品单可以审核通过。")
    cleaned_note = note.strip()
    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    now = timezone.now()
    _record_workflow_stage(
        sample_request=sample_request,
        stage=SampleWorkflowStage.PMC_APPROVED,
        actor_employee=actor_employee,
        note=cleaned_note or "PMC 审核通过。",
        operated_at=now,
    )
    sample_request.status = SampleRequestStatus.METALWORK_PENDING
    sample_request.save(update_fields=["status", "updated_at"])
    _write_sample_records(
        sample_request=sample_request,
        action="PMC_APPROVED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=cleaned_note or "PMC 审核通过。",
    )
    return sample_request


@transaction.atomic
def upload_sample_parameters(
    *,
    sample_request,
    parameter_type,
    note,
    business_file,
    actor_employee,
    request,
):
    """上传一张金工或裁剪参数图片；两个工序可以任意顺序、多次补充。"""

    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    configuration = {
        "metalwork": {
            "stage": SampleWorkflowStage.METALWORK_PARAMETERS,
            "parameter_type": "METALWORK",
            "file_role": "METALWORK_PARAMETERS",
            "action": "METALWORK_PARAMETERS_UPLOADED",
            "default_note": "已上传金工参数。",
        },
        "cutting": {
            "stage": SampleWorkflowStage.CUTTING_PARAMETERS,
            "parameter_type": "CUTTING",
            "file_role": "CUTTING_PARAMETERS",
            "action": "CUTTING_PARAMETERS_UPLOADED",
            "default_note": "已上传裁剪参数。",
        },
    }.get(parameter_type)
    if configuration is None:
        raise ValidationError({"parameter_type": "参数类型不正确。"})
    if sample_request.application_payload_hash:
        configuration["default_note"] = "已上传金工参数。" if parameter_type == "metalwork" else "已上传裁剪参数。"
    if business_file is None:
        raise ValidationError({"file": "请上传参数文件。"})
    if sample_request.status not in {
        SampleRequestStatus.METALWORK_PENDING,
        SampleRequestStatus.CUTTING_PENDING,
        SampleRequestStatus.PRODUCTION_PENDING,
    }:
        raise Conflict("当前样品单不允许执行参数图片上传。")
    if sample_request.application_payload_hash:
        from .production_services import production_ready
        if sample_request.archived_at or sample_request.customer_account.archived_at or not production_ready(sample_request):
            raise Conflict("材料尚未齐备或样品已归档，不能上传参数。")

    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    now = timezone.now()
    cleaned_note = note.strip()
    SampleParameterImage.objects.create(
        sample_request=sample_request,
        parameter_type=configuration["parameter_type"],
        business_file=business_file,
        uploaded_by_employee=actor_employee,
        uploaded_at=now,
    )
    SampleWorkflowRecord.objects.get_or_create(
        sample_request=sample_request,
        stage=configuration["stage"],
        defaults={
            "business_file": None,
            "note": cleaned_note or configuration["default_note"],
            "operated_by_employee": actor_employee,
            "operated_at": now,
        },
    )
    metalwork_ready = sample_request.parameter_images.filter(
        parameter_type="METALWORK", archived_at__isnull=True
    ).exists()
    cutting_ready = sample_request.parameter_images.filter(
        parameter_type="CUTTING", archived_at__isnull=True
    ).exists()
    if metalwork_ready and cutting_ready:
        if sample_request.application_payload_hash:
            from .production_services import finish_production_if_ready
            finish_production_if_ready(sample_request, actor_employee=actor_employee)
        else:
            sample_request.status = SampleRequestStatus.FINISHED
            sample_request.save(update_fields=["status", "updated_at"])
            if not SampleWorkflowRecord.objects.filter(
                sample_request=sample_request,
                stage=SampleWorkflowStage.WORKFLOW_FINISHED,
            ).exists():
                _record_workflow_stage(
                    sample_request=sample_request,
                    stage=SampleWorkflowStage.WORKFLOW_FINISHED,
                    actor_employee=actor_employee,
                    note="金工和裁剪参数图片均已上传，样品单流程结束。",
                    operated_at=now,
                )
                _finish_sla(sample_request, False, now)
    else:
        sample_request.status = (
            SampleRequestStatus.CUTTING_PENDING
            if metalwork_ready
            else SampleRequestStatus.METALWORK_PENDING
        )
        sample_request.save(update_fields=["status", "updated_at"])
    _write_sample_records(
        sample_request=sample_request,
        action=configuration["action"],
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=cleaned_note or configuration["default_note"],
    )
    return sample_request


@transaction.atomic
def delete_sample_parameter_image(*, sample_request, image_id, actor_employee, request):
    """入库前直接删除一张参数图片，并按剩余图片回退待上传状态。"""
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status in {
        SampleRequestStatus.FINISHED,
        SampleRequestStatus.CANCELLED,
        SampleRequestStatus.REJECTED,
    }:
        raise Conflict("样品已进入终态，不能删除参数图片。")
    image = sample_request.parameter_images.select_related("business_file").filter(
        pk=image_id, archived_at__isnull=True
    ).first()
    if image is None:
        raise ValidationError({"image_id": "参数图片不存在或已删除。"})
    before_data = model_snapshot(sample_request, SAMPLE_FIELDS)
    business_file = image.business_file
    now = timezone.now()
    image.archived_at = now
    image.archived_by_employee = actor_employee
    image.archive_reason = "用户直接删除参数图片。"
    image.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
    metalwork_ready = sample_request.parameter_images.filter(
        parameter_type="METALWORK", archived_at__isnull=True
    ).exists()
    cutting_ready = sample_request.parameter_images.filter(
        parameter_type="CUTTING", archived_at__isnull=True
    ).exists()
    if metalwork_ready and cutting_ready:
        if sample_request.application_payload_hash:
            from .production_services import finish_production_if_ready
            finish_production_if_ready(sample_request, actor_employee=actor_employee)
    else:
        sample_request.status = (
            SampleRequestStatus.CUTTING_PENDING
            if metalwork_ready
            else SampleRequestStatus.METALWORK_PENDING
        )
        sample_request.save(update_fields=["status", "updated_at"])
    _write_sample_records(
        sample_request=sample_request,
        action="PARAMETER_IMAGE_DELETED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=f"删除{image.get_parameter_type_display()}参数图片。",
    )
    # 参数图片采用软归档；业务文件保留为审计证据，归档后不会再出现在下载查询中。
    business_file.archived_at = now
    business_file.archived_by_employee = actor_employee
    business_file.archive_reason = "关联参数图片已删除。"
    business_file.save(update_fields=["archived_at", "archived_by_employee", "archive_reason", "updated_at"])
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
    approver_employee = validated_data.pop("approver_employee_id", None)
    requested_decision = validated_data["fee_decision"]
    if requested_decision == SampleFeeDecision.WAIVED:
        # 豁免在审批通过前始终保持“待决定”，不能提前影响后续寄送判断。
        validated_data["fee_decision"] = SampleFeeDecision.PENDING
        validated_data["requested_decision"] = SampleFeeDecision.WAIVED
        validated_data["approval_status"] = FeeApprovalStatus.PENDING
    else:
        validated_data["requested_decision"] = requested_decision
        validated_data["approval_status"] = FeeApprovalStatus.NOT_REQUIRED
    now = timezone.now()
    sample_request.fee_records.filter(superseded_at__isnull=True).update(superseded_at=now, updated_at=now)
    from apps.access_control import module_policy
    if module_policy.enabled():
        old_ids = SampleApprovalLink.objects.filter(sample_request=sample_request).values('approval_request_id')
        old_approvals = ApprovalRequest.objects.select_for_update().filter(pk__in=old_ids, approval_type='SAMPLE_FEE_WAIVER', status=ApprovalStatus.PENDING)
        for old_approval in old_approvals:
            old_approval.status = ApprovalStatus.CANCELLED
            old_approval.decision_note = '费用决策已重新提交，本次审批已失效。'
            old_approval.decided_at = now
            old_approval.save(update_fields=['status', 'decision_note', 'decided_at', 'updated_at'])
            write_audit_log(object_type='APPROVAL_REQUEST', object_id=old_approval.pk,
                action='SUPERSEDED', actor_employee=actor_employee,
                after_data={'status': ApprovalStatus.CANCELLED}, request=request)
    record = SampleFeeRecord.objects.create(
        sample_request=sample_request,
        decided_by_employee=actor_employee,
        decided_at=now,
        **validated_data,
    )
    approval = None
    if requested_decision == SampleFeeDecision.WAIVED:
        approval = ApprovalRequest.objects.create(
            current_approver_employee=approver_employee,
            requested_by_employee=actor_employee,
            approval_type="SAMPLE_FEE_WAIVER",
            request_reason=record.decision_reason,
            submitted_at=now,
        )
        SampleApprovalLink.objects.create(sample_request=sample_request, approval_request=approval)
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
            "approval_id": str(approval.pk) if approval else None,
            "fee_decision": record.fee_decision,
            "requested_decision": record.requested_decision,
            "amount": str(record.amount),
            "currency_code": record.currency_code,
            "sample_fee_amount": str(record.sample_fee_amount),
            "shipping_fee_amount": str(record.shipping_fee_amount),
            "discount_amount": str(record.discount_amount),
            "payable_amount": str(record.payable_amount),
            "approval_status": record.approval_status,
            "verification_status": record.verification_status,
            "decision_reason": record.decision_reason,
        },
        request=request,
    )
    write_customer_timeline(
        customer=sample_request.customer_account,
        event_type="SAMPLE_FEE_DECIDED",
        title=f"{sample_request.request_number} 费用：{record.get_requested_decision_display()}",
        summary=record.decision_reason,
        source_type="SAMPLE_FEE_RECORD",
        source_id=record.pk,
        actor_employee=actor_employee,
    )
    return record, sample_request


@transaction.atomic
def decide_fee_waiver_approval(*, sample_request, approval_id, approved, note, actor_employee, request):
    """决定样品费用豁免，审批人和样品版本必须同时匹配。"""
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    link = SampleApprovalLink.objects.select_related("approval_request").select_for_update().filter(
        sample_request=sample_request,
        approval_request_id=approval_id,
        approval_request__approval_type="SAMPLE_FEE_WAIVER",
    ).first()
    if link is None:
        raise Conflict("费用豁免审批不存在或不属于当前样品申请。")
    approval = ApprovalRequest.objects.select_for_update().get(pk=link.approval_request_id)
    if approval.status != ApprovalStatus.PENDING:
        raise Conflict("该费用豁免审批已经处理。")
    if approval.current_approver_employee_id != getattr(actor_employee, "pk", None):
        raise PermissionDenied("只有当前审批人可以处理费用豁免。")
    from apps.access_control import module_policy
    module_policy.prohibit_self_approval(actor_employee, approval.requested_by_employee_id)
    record = SampleFeeRecord.objects.select_for_update().filter(
        sample_request=sample_request,
        superseded_at__isnull=True,
        requested_decision=SampleFeeDecision.WAIVED,
        approval_status=FeeApprovalStatus.PENDING,
    ).first()
    if record is None:
        raise Conflict("当前没有待处理的费用豁免申请。")
    if module_policy.enabled():
        from apps.audit.models import AuditLog
        if not AuditLog.objects.filter(object_type='SAMPLE_FEE_RECORD', object_id=record.pk,
                action='DECIDED', after_data__approval_id=str(approval.pk),
                actor_employee_id=approval.requested_by_employee_id).exists():
            raise Conflict('审批与当前费用记录缺少可靠对应，请重新提交费用决策。')
    now = timezone.now()
    approval.status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
    approval.decision_note = note
    approval.decided_at = now
    approval.save(update_fields=["status", "decision_note", "decided_at", "updated_at"])
    before_data = {
        "fee_decision": record.fee_decision,
        "approval_status": record.approval_status,
    }
    record.approval_status = FeeApprovalStatus.APPROVED if approved else FeeApprovalStatus.REJECTED
    record.fee_decision = SampleFeeDecision.WAIVED if approved else SampleFeeDecision.PENDING
    record.decided_at = now
    record.save(update_fields=["approval_status", "fee_decision", "decided_at", "updated_at"])
    _touch(sample_request)
    action = "WAIVER_APPROVED" if approved else "WAIVER_REJECTED"
    write_audit_log(
        object_type="SAMPLE_FEE_RECORD",
        object_id=record.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action=action,
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={
            "approval_id": str(approval.pk),
            "fee_decision": record.fee_decision,
            "approval_status": record.approval_status,
            "note": note,
        },
        request=request,
    )
    write_customer_timeline(
        customer=sample_request.customer_account,
        event_type=f"SAMPLE_FEE_{action}",
        title=f"{sample_request.request_number} 费用豁免{approval.get_status_display()}",
        summary=note,
        source_type="APPROVAL_REQUEST",
        source_id=approval.pk,
        actor_employee=actor_employee,
    )
    return record, approval, sample_request


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


def _record_manual_shipment_event(
    *, shipment, event_type, actor_employee, note, occurred_at, material_status=""
):
    """记录人工物流事实，事件标识和版本为后续承运商同步保留幂等边界。"""

    last_version = (
        shipment.events.order_by("-source_object_version", "-id")
        .values_list("source_object_version", flat=True)
        .first()
        or 0
    )
    event_version = last_version + 1
    payload_snapshot = {
        "shipment_status": shipment.status,
        "carrier_code": shipment.carrier_code,
        "tracking_number": shipment.tracking_number,
        "note": note,
    }
    if material_status:
        payload_snapshot["material_status"] = material_status
    return SampleShipmentEvent.objects.create(
        sample_shipment=shipment,
        event_type=event_type,
        source=ShipmentEventSource.MANUAL,
        event_identifier=f"MANUAL:{shipment.pk}:{event_type}:{event_version}",
        source_object_version=event_version,
        occurred_at=occurred_at,
        synchronized_at=occurred_at,
        payload_snapshot=payload_snapshot,
        recorded_by_employee=actor_employee,
    )


def _ensure_feedback_task(*, sample_request, shipment, actor_employee, request, occurred_at):
    """一张寄送记录只生成一条签收反馈待办，重复事件不得重复建任务。"""

    automation_key = f"SAMPLE_DELIVERED_FEEDBACK:{shipment.pk}"
    task = BusinessTask.objects.filter(automation_key=automation_key).first()
    if task is not None:
        return task, False
    task = create_task(
        validated_data={
            "assignee_employee": sample_request.owner_employee,
            "contact": sample_request.customer_contact,
            "title": f"跟进样品反馈 {sample_request.request_number}",
            "description": "样品已人工签收，请在 24 小时内记录客户反馈与确认结果。",
            "priority": TaskPriority.NORMAL,
            "task_type": TaskType.SAMPLE_FEEDBACK,
            "origin_type": TaskOriginType.BUSINESS_EVENT,
            "origin_code": "SAMPLE_DELIVERED",
            "due_at": occurred_at + timedelta(hours=24),
            "automation_key": automation_key,
            "source_type": "SAMPLE_REQUEST",
            "source_id": str(sample_request.pk),
        },
        actor_employee=actor_employee,
        request=request,
        resolved_source=(sample_request, sample_request.customer_account, SampleTaskLink, "sample_request"),
    )
    return task, True


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
    _record_manual_shipment_event(
        shipment=shipment,
        event_type=ShipmentEventType.SHIPPED,
        actor_employee=actor_employee,
        note=action_notes,
        occurred_at=now,
    )
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
    _record_manual_shipment_event(
        shipment=shipment,
        event_type=ShipmentEventType.DELIVERED,
        actor_employee=actor_employee,
        note=note or "人工标记签收。",
        occurred_at=now,
    )
    feedback_task, feedback_task_created = _ensure_feedback_task(
        sample_request=sample_request,
        shipment=shipment,
        actor_employee=actor_employee,
        request=request,
        occurred_at=now,
    )
    _write_sample_records(
        sample_request=sample_request,
        action="DELIVERED",
        actor_employee=actor_employee,
        request=request,
        note=(note or "人工标记签收。") + (
            f" 已创建反馈待办 {feedback_task.task_number}。" if feedback_task_created else ""
        ),
    )
    return shipment, sample_request


@transaction.atomic
def mark_shipment_exception(*, shipment, note, actor_employee, request):
    """只记录当前人工异常事实，不覆盖已签收等更高阶段的运输结果。"""

    shipment = SampleShipment.objects.select_for_update().get(pk=shipment.pk)
    require_matching_etag(request, shipment)
    if shipment.status in {SampleShipmentStatus.DELIVERED, SampleShipmentStatus.CANCELLED}:
        raise Conflict("已签收或已取消的寄送记录不能回退为物流异常。")
    sample_request = SampleRequest.objects.select_for_update().get(pk=shipment.sample_request_id)
    now = timezone.now()
    shipment.status = SampleShipmentStatus.EXCEPTION
    shipment.notes = "\n".join(part for part in [shipment.notes, f"物流异常：{note}"] if part)
    shipment.save(update_fields=["status", "notes", "updated_at"])
    _record_manual_shipment_event(
        shipment=shipment,
        event_type=ShipmentEventType.EXCEPTION,
        actor_employee=actor_employee,
        note=note,
        occurred_at=now,
    )
    _touch(sample_request)
    _write_sample_records(
        sample_request=sample_request,
        action="SHIPMENT_EXCEPTION",
        actor_employee=actor_employee,
        request=request,
        note=note,
    )
    return shipment, sample_request


@transaction.atomic
def record_shipment_progress(*, shipment, validated_data, actor_employee, request):
    """记录运输中的实际物料进度，不改变寄送或样品申请状态。"""

    shipment = SampleShipment.objects.select_for_update().get(pk=shipment.pk)
    require_matching_etag(request, shipment)
    if shipment.status not in {SampleShipmentStatus.SHIPPED, SampleShipmentStatus.EXCEPTION}:
        raise Conflict("只有运输中或异常中的寄送记录可以更新物料进度。")
    sample_request = SampleRequest.objects.select_for_update().get(pk=shipment.sample_request_id)
    material_status = validated_data["material_status"].strip()
    occurred_at = validated_data["occurred_at"]
    _touch(shipment)
    _record_manual_shipment_event(
        shipment=shipment,
        event_type=ShipmentEventType.PROGRESS,
        actor_employee=actor_employee,
        note=material_status,
        material_status=material_status,
        occurred_at=occurred_at,
    )
    _touch(sample_request)
    _write_sample_records(
        sample_request=sample_request,
        action="SHIPMENT_PROGRESS_UPDATED",
        actor_employee=actor_employee,
        request=request,
        note=f"物料进度：{material_status}",
    )
    return shipment, sample_request


@transaction.atomic
def create_feedback(*, sample_request, validated_data, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status not in {
        SampleRequestStatus.DELIVERED,
        SampleRequestStatus.FEEDBACK_PENDING,
        SampleRequestStatus.CONFIRMED,
        SampleRequestStatus.COMPLETED,
    }:
        raise Conflict("只有待反馈或已完成的样品申请可以记录反馈。")
    feedback = SampleFeedback.objects.create(
        sample_request=sample_request,
        recorded_by_employee=actor_employee,
        **validated_data,
    )
    if sample_request.status == SampleRequestStatus.DELIVERED:
        sample_request.status = SampleRequestStatus.FEEDBACK_PENDING
        sample_request.save(update_fields=["status", "updated_at"])
    for feedback_task in BusinessTask.objects.filter(
        sample_links__sample_request=sample_request,
        task_type=TaskType.SAMPLE_FEEDBACK,
        status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
        archived_at__isnull=True,
    ).distinct():
        transition_task(
            task=feedback_task,
            action="COMPLETED",
            note=f"已记录样品反馈：{feedback.feedback_content[:300]}",
            actor_employee=actor_employee,
            request=request,
            enforce_etag=False,
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
            "confirmation_result": feedback.confirmation_result,
            "confirmation_source": feedback.confirmation_source,
            "source_object_version": feedback.source_object_version,
            "rejection_reason": feedback.rejection_reason,
            "corrective_action_request": feedback.corrective_action_request,
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
def create_requotation_from_feedback(
    *,
    sample_request,
    feedback_id,
    source_version,
    valid_until,
    notes,
    actor_employee,
    request,
):
    """从样品反馈生成可追溯报价草稿，重复提交返回同一结果。"""

    sample_request = SampleRequest.objects.select_for_update(of=("self",)).select_related(
        "customer_account",
        "transaction_entity",
        "owner_employee",
        "source_inquiry",
        "source_quotation_version__quotation",
    ).get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    feedback = SampleFeedback.objects.select_for_update(of=("self",)).select_related(
        "resulting_quotation_version__quotation",
        "requotation_source_version__quotation",
    ).get(pk=feedback_id, sample_request=sample_request)

    sales_policy.require_customer(request, "quotations.view_quotationversion", source_version.quotation.customer_account)
    sales_policy.require_customer(request, "quotations.add_quotationversion", sample_request.customer_account)
    if feedback.resulting_quotation_version_id:
        sales_policy.require_customer(request, "quotations.view_quotationversion", feedback.resulting_quotation_version.quotation.customer_account)
        if feedback.requotation_source_version_id != source_version.pk:
            raise Conflict("该反馈已经基于其他历史报价生成再报价，不能重复更换复制来源。")
        return (
            feedback.resulting_quotation_version.quotation,
            feedback.resulting_quotation_version,
            sample_request,
            False,
            True,
        )
    if source_version.quotation.customer_account_id != sample_request.customer_account_id:
        raise ValidationError({"source_quotation_version_id": ["只能选择同客户的历史报价版本。"]})
    if source_version.status == "VOID":
        raise Conflict("已作废的报价版本不能作为再报价复制来源。")

    origin_quotation = None
    if sample_request.source_quotation_version_id:
        candidate = sample_request.source_quotation_version.quotation
        if candidate.outcome_status == QuotationOutcomeStatus.OPEN:
            origin_quotation = candidate
    elif source_version.quotation.outcome_status == QuotationOutcomeStatus.OPEN:
        origin_quotation = source_version.quotation

    if origin_quotation is None:
        sales_policy.require_customer(request, "quotations.add_quotation", sample_request.customer_account)
    if origin_quotation is None and not sales_policy.has_permission(request, "quotations.add_quotation"):
        raise PermissionDenied("来源报价已经终态，创建新报价需要报价建档权限。")

    feedback_note = notes.strip() or (
        f"样品 {sample_request.request_number} 反馈再报价：{feedback.feedback_content[:1000]}"
    )
    quotation, version, created_new_quotation = create_requotation_draft(
        source_version=source_version,
        target_quotation=origin_quotation,
        new_quotation_data={
            "customer_account": sample_request.customer_account,
            "transaction_entity": sample_request.transaction_entity or source_version.quotation.transaction_entity,
            "source_inquiry": sample_request.source_inquiry,
            "owner_employee": sales_policy.primary_owner(sample_request.customer_account) if sales_policy.enabled() else sample_request.owner_employee,
            "subject": source_version.quotation.subject,
        },
        valid_until=valid_until,
        feedback_note=feedback_note,
        actor_employee=actor_employee,
        request=request,
    )
    now = timezone.now()
    feedback.requotation_source_version = source_version
    feedback.resulting_quotation_version = version
    feedback.requotation_created_by_employee = actor_employee
    feedback.requotation_created_at = now
    feedback.save(update_fields=[
        "requotation_source_version",
        "resulting_quotation_version",
        "requotation_created_by_employee",
        "requotation_created_at",
        "updated_at",
    ])
    _touch(sample_request)
    write_audit_log(
        object_type="SAMPLE_FEEDBACK",
        object_id=feedback.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=sample_request.customer_account_id,
        action="REQUOTATION_CREATED",
        actor_employee=actor_employee,
        after_data={
            "source_quotation_version_id": str(source_version.pk),
            "resulting_quotation_version_id": str(version.pk),
            "created_new_quotation": created_new_quotation,
        },
        request=request,
    )
    write_customer_timeline(
        customer=sample_request.customer_account,
        event_type="SAMPLE_FEEDBACK_REQUOTED",
        title=f"{sample_request.request_number} 已创建再报价",
        summary=f"{quotation.quotation_number} V{version.version_number}",
        source_type="SAMPLE_FEEDBACK",
        source_id=feedback.pk,
        actor_employee=actor_employee,
    )
    return quotation, version, sample_request, created_new_quotation, False


@transaction.atomic
def link_sample_file(*, sample_request, business_file, file_role, actor_employee, request):
    sample_request = SampleRequest.objects.select_for_update().get(pk=sample_request.pk)
    require_matching_etag(request, sample_request)
    if sample_request.status in {
        SampleRequestStatus.CONFIRMED,
        SampleRequestStatus.COMPLETED,
        SampleRequestStatus.FINISHED,
        SampleRequestStatus.REJECTED,
        SampleRequestStatus.CANCELLED,
    }:
        raise Conflict("终态样品申请不能再关联文件。")
    link = SampleFileLink.objects.create(
        sample_request=sample_request,
        business_file=business_file,
        file_role=file_role,
    )
    if file_role == "FEE_EVIDENCE":
        current_fee = SampleFeeRecord.objects.select_for_update().filter(
            sample_request=sample_request,
            superseded_at__isnull=True,
            fee_decision=SampleFeeDecision.PAID,
            verification_status=FeeVerificationStatus.PENDING,
        ).first()
        if current_fee is not None:
            current_fee.verification_status = FeeVerificationStatus.EVIDENCE_UPLOADED
            current_fee.save(update_fields=["verification_status", "updated_at"])
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
