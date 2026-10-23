from apps.access_control import sales_policy
import json
from datetime import timedelta, timezone as datetime_timezone

from django.core.serializers.json import DjangoJSONEncoder
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
    Inquiry,
    InquiryPriority,
    InquiryAssignmentHistory,
    InquiryDraftRevision,
    InquiryFileLink,
    InquiryItem,
    InquirySlaLink,
    InquiryStatus,
)
from .rich_text import rich_text_plain_text


class InquiryStateConflict(Conflict):
    def __init__(self, detail, code="INQUIRY_INVALID_STATUS"):
        self.api_error_code = code
        super().__init__(detail)


INQUIRY_FIELDS = [
    "customer_account",
    "transaction_entity",
    "customer_contact",
    "owner_employee",
    "inquiry_number",
    "priority",
    "status",
    "inquiry_source",
    "subject",
    "description",
    "received_at",
    "requested_due_at",
    "submitted_at",
    "source_system",
    "external_id",
    "customer_language_code",
    "trade_term_code",
    "trade_term_place",
    "delivery_requirement",
    "estimated_amount_min",
    "estimated_amount_max",
    "estimated_currency_code",
    "draft_version",
]
ITEM_FIELDS = [
    "inquiry",
    "line_number",
    "product_description",
    "specification",
    "color",
    "material",
    "quantity",
    "unit_code",
    "target_unit_price",
    "target_currency_code",
    "expected_date",
    "product_match_status",
    "notes",
    "product",
    "product_category",
    "product_unit",
    "product_color",
    "product_image",
    "product_number_snapshot",
    "product_code_snapshot",
    "item_number_snapshot",
    "customer_product_name_snapshot",
    "customer_specification_snapshot",
    "customer_unit_code_snapshot",
    "customer_color_snapshot",
    "customer_material_snapshot",
]


def prepare_inquiry_item_data(item_data, *, existing=None):
    """保存询盘产品时装配主档快照，同时保留客户原始文字。"""
    data = dict(item_data)
    product = data.get("product")
    if product is not None:
        # 同一关联的编辑继续使用单据快照，不重新套用后来变过的产品库默认值。
        if existing is not None and existing.product_id == product.pk:
            data["product_number_snapshot"] = existing.product_number_snapshot
            data["product_code_snapshot"] = existing.product_code_snapshot
            data["item_number_snapshot"] = existing.item_number_snapshot
        else:
            data["product_category"] = product.category
            data["product_unit"] = product.unit
            data["product_number_snapshot"] = product.product_number
            data["product_code_snapshot"] = product.product_code
            data["item_number_snapshot"] = product.product_item.item_number
    elif "product" in data:
        data["product_number_snapshot"] = ""
        data["product_code_snapshot"] = ""
        data["item_number_snapshot"] = ""
    data.setdefault(
        "customer_product_name_snapshot",
        getattr(existing, "customer_product_name_snapshot", data.get("product_description", "")),
    )
    data.setdefault(
        "customer_specification_snapshot",
        getattr(existing, "customer_specification_snapshot", data.get("specification", "")),
    )
    data.setdefault(
        "customer_unit_code_snapshot",
        getattr(existing, "customer_unit_code_snapshot", data.get("unit_code", "")),
    )
    data.setdefault(
        "customer_color_snapshot",
        getattr(existing, "customer_color_snapshot", data.get("color", "")),
    )
    data.setdefault(
        "customer_material_snapshot",
        getattr(existing, "customer_material_snapshot", data.get("material", "")),
    )
    return data


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


def _draft_snapshot(inquiry):
    """将当前草稿转为 JSON 安全快照，供重试与审计回溯。"""
    payload = {
        "inquiry": model_snapshot(inquiry, INQUIRY_FIELDS),
        "items": [model_snapshot(item, ITEM_FIELDS) for item in inquiry.items.order_by("line_number", "id")],
    }
    return json.loads(json.dumps(payload, cls=DjangoJSONEncoder))


def _record_draft_revision(*, inquiry, idempotency_key, actor_employee):
    inquiry.draft_version += 1
    inquiry.save(update_fields=["draft_version", "updated_at"])
    return InquiryDraftRevision.objects.create(
        inquiry=inquiry,
        revision_number=inquiry.draft_version,
        idempotency_key=idempotency_key,
        snapshot=_draft_snapshot(inquiry),
        saved_by_employee=actor_employee,
    )


@transaction.atomic
def create_inquiry(*, validated_data, actor_employee, request):
    if actor_employee is None:
        raise ValidationError({"owner_employee": "当前账号未关联有效员工档案，不能创建询盘。"})
    customer = validated_data["customer_account"]
    sales_policy.require_customer(request, "inquiries.add_inquiry", customer)
    owner = sales_policy.primary_owner(customer) if sales_policy.enabled() else actor_employee
    sales_policy.validate_document_owner(request, customer, owner)
    items = validated_data.pop("items", [])
    idempotency_key = validated_data.pop("idempotency_key", "")
    validated_data.pop("owner_employee", None)
    if idempotency_key:
        existing = Inquiry.objects.filter(creation_idempotency_key=idempotency_key).first()
        if existing:
            if existing.customer_account_id != validated_data["customer_account"].pk:
                raise ValidationError({"idempotency_key": "该幂等键已用于其他客户的询盘。"})
            return existing
    inquiry = Inquiry.objects.create(
        inquiry_number=next_business_number("INQUIRY"),
        status=InquiryStatus.DRAFT,
        owner_employee=owner,
        assigned_at=timezone.now(),
        creation_idempotency_key=idempotency_key,
        **validated_data,
    )
    inquiry.customer_snapshot = {
        "customer_id": str(inquiry.customer_account_id),
        "customer_name": inquiry.customer_account.account_name,
        "country_code": getattr(inquiry.customer_account, "primary_country_code", ""),
    }
    inquiry.source_snapshot = {"source_code": inquiry.inquiry_source}
    inquiry.save(update_fields=["customer_snapshot", "source_snapshot", "updated_at"])
    used_numbers = {item["line_number"] for item in items if "line_number" in item}
    created_items = []
    for index, item_data in enumerate(items, start=1):
        item_data = prepare_inquiry_item_data(item_data)
        created_items.append(
            InquiryItem(
                inquiry=inquiry,
                line_number=_line_number(item_data, used_numbers, index),
                **item_data,
            )
        )
    InquiryItem.objects.bulk_create(created_items)
    if idempotency_key:
        _record_draft_revision(
            inquiry=inquiry,
            idempotency_key=idempotency_key,
            actor_employee=actor_employee,
        )
    _write_inquiry_records(
        inquiry=inquiry,
        action="CREATED",
        actor_employee=actor_employee,
        request=request,
        note=f"同时创建 {len(created_items)} 条询价明细。",
    )
    return inquiry


@transaction.atomic
def save_inquiry_draft(*, inquiry, validated_data, actor_employee, request):
    """原子保存草稿头部和完整明细；相同幂等键可安全重试。"""
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    idempotency_key = validated_data.pop("idempotency_key")
    if InquiryDraftRevision.objects.filter(inquiry=inquiry, idempotency_key=idempotency_key).exists():
        return inquiry
    require_matching_etag(request, inquiry)
    _ensure_draft(inquiry)
    items_data = validated_data.pop("items", None)
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    for field_name, value in validated_data.items():
        setattr(inquiry, field_name, value)
    if validated_data:
        inquiry.save(update_fields=[*validated_data.keys(), "updated_at"])

    if items_data is not None:
        if len(items_data) > 200:
            raise ValidationError({"items": "单张询价最多包含 200 条明细。"})
        existing = {str(item.pk): item for item in InquiryItem.objects.select_for_update().filter(inquiry=inquiry)}
        retained_ids = set()
        used_numbers = set()
        for index, raw_item in enumerate(items_data, start=1):
            item_id = str(raw_item.get("id", ""))
            item_data = prepare_inquiry_item_data(raw_item, existing=existing.get(item_id))
            item_id = str(item_data.pop("id", item_id))
            line_number = _line_number(item_data, used_numbers, index)
            if item_id:
                item = existing.get(item_id)
                if item is None:
                    raise ValidationError({"items": "明细不属于当前询盘。"})
                retained_ids.add(item_id)
                for field_name, value in item_data.items():
                    setattr(item, field_name, value)
                item.line_number = line_number
                item.save(update_fields=[*item_data.keys(), "line_number", "updated_at"])
            else:
                InquiryItem.objects.create(inquiry=inquiry, line_number=line_number, **item_data)
        for item_id, item in existing.items():
            if item_id not in retained_ids:
                item.delete()

    _record_draft_revision(
        inquiry=inquiry,
        idempotency_key=idempotency_key,
        actor_employee=actor_employee,
    )
    _write_inquiry_records(
        inquiry=inquiry,
        action="DRAFT_SAVED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=f"草稿已保存为 V{inquiry.draft_version}。",
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
        raise InquiryStateConflict("询盘提交后明细只读；如需更正，请取消原询盘并新建询盘。")


@transaction.atomic
def create_inquiry_item(*, inquiry, validated_data, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    _ensure_draft(inquiry)
    if inquiry.items.count() >= 200:
        raise ValidationError({"detail": "单张询价最多包含 200 条明细。"})
    item_data = prepare_inquiry_item_data(validated_data)
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
    validated_data = prepare_inquiry_item_data(validated_data, existing=item)
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
def set_inquiry_item_product_image(*, item, business_file, actor_employee, request):
    from apps.files.reference_guards import require_non_finance_receipt_file
    require_non_finance_receipt_file(business_file)
    inquiry = Inquiry.objects.select_for_update().get(pk=item.inquiry_id)
    require_matching_etag(request, inquiry)
    _ensure_draft(inquiry)
    item = InquiryItem.objects.select_for_update().get(pk=item.pk)
    before_data = model_snapshot(item, ITEM_FIELDS)
    item.product_image = business_file
    item.save(update_fields=["product_image", "updated_at"])
    _touch_inquiry(inquiry)
    write_audit_log(
        object_type="INQUIRY_ITEM",
        object_id=item.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action="PRODUCT_IMAGE_UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(item, ITEM_FIELDS),
        request=request,
    )
    return item, inquiry


@transaction.atomic
def remove_inquiry_item_product_image(*, item, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=item.inquiry_id)
    require_matching_etag(request, inquiry)
    _ensure_draft(inquiry)
    item = InquiryItem.objects.select_for_update().get(pk=item.pk)
    before_data = model_snapshot(item, ITEM_FIELDS)
    item.product_image = None
    item.save(update_fields=["product_image", "updated_at"])
    _touch_inquiry(inquiry)
    write_audit_log(
        object_type="INQUIRY_ITEM",
        object_id=item.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=inquiry.customer_account_id,
        action="PRODUCT_IMAGE_REMOVED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(item, ITEM_FIELDS),
        request=request,
    )
    return inquiry


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


def _start_sla(inquiry, started_at, stage_code, *, context=None):
    """仅在当前阶段存在真实目标时建立 SLA，不虚构截止时间。"""
    existing = inquiry.sla_links.filter(stage_code=stage_code, is_current=True).select_related('sla_tracking').first()
    if existing:
        return existing
    policy = SlaPolicy.objects.filter(
        target_type="INQUIRY",
        is_enabled=True,
        archived_at__isnull=True,
    ).order_by("policy_code").first()
    if policy is None:
        return None
    target_minutes = {'FIRST_RESPONSE': policy.response_minutes, 'REQUIREMENT_CONFIRMATION': policy.resolution_minutes}.get(stage_code, policy.config_data.get('stage_minutes', {}).get(stage_code))
    if not target_minutes:
        return None
    from copy import deepcopy
    from .worktime import add_work_minutes
    calendar = deepcopy(policy.config_data.get("work_calendar"))
    deadline = add_work_minutes(started_at, target_minutes, calendar) if calendar else started_at + timedelta(minutes=target_minutes)
    snapshot = {}
    if calendar:
        snapshot = {
            "work_calendar": calendar,
            "warning_at": (started_at if target_minutes <= 30 else add_work_minutes(started_at, target_minutes - 30, calendar)).astimezone(datetime_timezone.utc).isoformat(),
        }
    tracking = SlaTracking.objects.create(
        sla_policy=policy,
        status=SlaTrackingStatus.RUNNING,
        started_at=started_at,
        next_deadline_at=deadline,
        tracking_data={
            **(context or {}),
            "target_kind": "RESPONSE" if stage_code == "FIRST_RESPONSE" else "RESOLUTION",
            "target_minutes": target_minutes,
            "round_number": inquiry.sla_links.filter(stage_code=stage_code).count() + 1,
            **snapshot,
        },
    )
    return InquirySlaLink.objects.create(
        inquiry=inquiry,
        sla_tracking=tracking,
        stage_code=stage_code,
        is_current=True,
    )


def _finish_sla(inquiry, target_status, finished_at, stage_code=None, *, reason=''):
    links = InquirySlaLink.objects.select_related("sla_tracking").filter(inquiry=inquiry, is_current=True)
    if stage_code:
        links = links.filter(stage_code=stage_code)
    for link in links:
        tracking = link.sla_tracking
        if tracking.status not in {SlaTrackingStatus.RUNNING, SlaTrackingStatus.BREACHED}:
            continue
        if target_status == SlaTrackingStatus.CANCELLED:
            if tracking.next_deadline_at and finished_at > tracking.next_deadline_at and not tracking.breached_at:
                tracking.breached_at = tracking.next_deadline_at
            tracking.status = SlaTrackingStatus.CANCELLED
        elif tracking.status == SlaTrackingStatus.BREACHED or (tracking.next_deadline_at and finished_at > tracking.next_deadline_at):
            tracking.status = SlaTrackingStatus.BREACHED
            tracking.breached_at = tracking.breached_at or tracking.next_deadline_at or finished_at
        else:
            tracking.status = SlaTrackingStatus.MET
        tracking.completed_at = finished_at
        if reason:
            tracking.tracking_data = {**tracking.tracking_data, 'completion_reason': reason}
        tracking.save(update_fields=["status", "breached_at", "completed_at", "tracking_data", "updated_at"])
        link.is_current = False
        link.save(update_fields=["is_current", "updated_at"])


def _quotation_facts(inquiry):
    """询盘端仅读取报价事实，绝不创建或修改报价。"""
    from apps.quotations.models import Quotation, QuotationVersionStatus

    quotations = Quotation.objects.filter(source_inquiry=inquiry, archived_at__isnull=True)
    return {
        "has_quotation": quotations.exists(),
        "has_sent_version": quotations.filter(versions__status=QuotationVersionStatus.SENT).exists(),
    }


@transaction.atomic
def transition_inquiry(*, inquiry, action, note, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    transitions = {
        "SUBMITTED": ({InquiryStatus.DRAFT}, InquiryStatus.NEW),
        "STARTED": ({InquiryStatus.NEW}, InquiryStatus.ANALYZING),
        "RESPONDED": ({InquiryStatus.NEW}, InquiryStatus.ANALYZING),
        "CONFIRMED_REQUIREMENTS": ({InquiryStatus.ANALYZING}, InquiryStatus.READY_FOR_QUOTE),
        "SYNCED_QUOTATION": ({InquiryStatus.READY_FOR_QUOTE}, InquiryStatus.QUOTING),
        "MARKED_QUOTED": ({InquiryStatus.QUOTING}, InquiryStatus.QUOTED),
        "FOLLOW_UP": ({InquiryStatus.QUOTED}, InquiryStatus.FOLLOW_UP),
        "MARKED_LOST": (
            {InquiryStatus.NEW, InquiryStatus.ANALYZING, InquiryStatus.READY_FOR_QUOTE, InquiryStatus.QUOTING, InquiryStatus.QUOTED, InquiryStatus.FOLLOW_UP},
            InquiryStatus.LOST,
        ),
        "CLOSED": (
            {InquiryStatus.NEW, InquiryStatus.ANALYZING, InquiryStatus.READY_FOR_QUOTE, InquiryStatus.QUOTING, InquiryStatus.QUOTED, InquiryStatus.FOLLOW_UP, InquiryStatus.LOST},
            InquiryStatus.CLOSED,
        ),
        "CANCELLED": (
            {InquiryStatus.DRAFT, InquiryStatus.NEW, InquiryStatus.ANALYZING, InquiryStatus.READY_FOR_QUOTE, InquiryStatus.QUOTING, InquiryStatus.QUOTED, InquiryStatus.FOLLOW_UP},
            InquiryStatus.CANCELLED,
        ),
    }
    allowed_statuses, target_status = transitions[action]
    if inquiry.status not in allowed_statuses:
        raise InquiryStateConflict(f"当前询盘状态“{inquiry.get_status_display()}”不允许执行此操作。")
    if action == "SUBMITTED" and inquiry.customer_contact_id is None:
        raise InquiryStateConflict(
            "正式提交前必须选择有效联系人。请返回编辑页补充联系人后再提交。",
            "INQUIRY_CONTACT_REQUIRED",
        )
    if action == "SUBMITTED" and not inquiry.items.exists():
        raise InquiryStateConflict(
            "询盘至少包含一条产品明细后才能提交。请返回编辑页补充产品。",
            "INQUIRY_ITEMS_REQUIRED",
        )
    if action == "RESPONDED" and not rich_text_plain_text(note).strip():
        raise ValidationError({"note": "记录首响时必须填写实际响应说明。"})
    if action == "CONFIRMED_REQUIREMENTS":
        if inquiry.customer_contact_id is None:
            raise InquiryStateConflict(
                "确认需求前必须补充客户联系人。",
                "INQUIRY_CONTACT_REQUIRED",
            )
        if not inquiry.items.exists():
            raise InquiryStateConflict(
                "确认需求前至少需要一条真实产品明细。",
                "INQUIRY_ITEMS_REQUIRED",
            )
    if action in {"SYNCED_QUOTATION", "MARKED_QUOTED"}:
        quotation_facts = _quotation_facts(inquiry)
        if action == "SYNCED_QUOTATION" and not quotation_facts["has_quotation"]:
            raise Conflict("尚无来源为当前询盘的真实报价，不能进入报价中。")
        if action == "MARKED_QUOTED" and not quotation_facts["has_sent_version"]:
            raise Conflict("尚无已发送的正式报价版本，不能标记为已报价。")
    now = timezone.now()
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    inquiry.status = target_status
    update_fields = ["status", "updated_at"]
    if action == "SUBMITTED":
        inquiry.submitted_at = now
        update_fields.append("submitted_at")
    if action in {"MARKED_LOST", "CLOSED", "CANCELLED"}:
        inquiry.close_reason_code = {
            "MARKED_LOST": "LOST",
            "CLOSED": "CLOSED",
            "CANCELLED": "CANCELLED",
        }[action]
        inquiry.close_reason_detail = note
        update_fields.extend(["close_reason_code", "close_reason_detail"])
    inquiry.save(update_fields=update_fields)
    if action == "SUBMITTED":
        _start_sla(inquiry, now, "FIRST_RESPONSE")
        if not inquiry.owner_employee_id:
            _start_sla(inquiry, now, 'ASSIGNMENT')
    elif action in {"STARTED", "RESPONDED"}:
        _finish_sla(inquiry, SlaTrackingStatus.MET, now, "FIRST_RESPONSE")
        _start_sla(inquiry, now, "REQUIREMENT_CONFIRMATION")
    elif action == "CONFIRMED_REQUIREMENTS":
        _finish_sla(inquiry, SlaTrackingStatus.MET, now, "REQUIREMENT_CONFIRMATION")
        _start_sla(inquiry, now, 'QUOTE_CREATION')
    # 报价计时由真实创建和首次发送推进，人工同步旧状态不能重放报价事件。
    elif action in {"CANCELLED", "MARKED_LOST"}:
        _finish_sla(inquiry, SlaTrackingStatus.CANCELLED, now)
    elif action == "CLOSED":
        _finish_sla(inquiry, SlaTrackingStatus.MET, now)
    _write_inquiry_records(
        inquiry=inquiry,
        action=action,
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note,
    )
    return inquiry


FOLLOW_UP_STATUSES = {
    InquiryStatus.ANALYZING,
    InquiryStatus.READY_FOR_QUOTE,
    InquiryStatus.QUOTING,
    InquiryStatus.QUOTED,
    InquiryStatus.FOLLOW_UP,
    InquiryStatus.QUOTE_ACCEPTED,
}


@transaction.atomic
def record_inquiry_communication(
    *,
    inquiry,
    communication_type,
    content,
    occurred_at,
    is_first_response,
    actor_employee,
    request,
):
    """记录真实沟通；首响会推进状态，后续跟进不覆盖询盘主状态。"""
    from apps.crm.services import create_communication

    inquiry = Inquiry.objects.select_for_update().select_related("customer_account").get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    if inquiry.customer_contact_id is None:
        raise InquiryStateConflict(
            "当前询盘缺少联系人。请先使用“补充联系人”，再记录客户沟通。",
            "INQUIRY_CONTACT_REQUIRED",
        )
    if is_first_response:
        if inquiry.status != InquiryStatus.NEW:
            raise InquiryStateConflict("只有待首响的询盘可以记录首响。")
    elif inquiry.status not in FOLLOW_UP_STATUSES:
        raise InquiryStateConflict(
            "当前阶段不能新增询盘跟进；销售订单确认后请到销售订单内继续跟踪。"
        )

    plain_content = rich_text_plain_text(content).strip()
    if not plain_content:
        raise ValidationError({"content": "必须填写实际沟通内容。"})
    communication = create_communication(
        validated_data={
            "customer_account": inquiry.customer_account,
            "communication_type": communication_type,
            "direction": "OUTBOUND",
            "subject": f"{inquiry.inquiry_number} {'记录首响' if is_first_response else '客户跟进'}",
            "content": content,
            "occurred_at": occurred_at,
            "participant_contacts": [inquiry.customer_contact],
            "inquiry": inquiry,
        },
        actor_employee=actor_employee,
        request=request,
    )

    if is_first_response:
        now = timezone.now()
        before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
        inquiry.status = InquiryStatus.ANALYZING
        inquiry.save(update_fields=["status", "updated_at"])
        _finish_sla(inquiry, SlaTrackingStatus.MET, now, "FIRST_RESPONSE")
        _start_sla(inquiry, now, "REQUIREMENT_CONFIRMATION")
        _write_inquiry_records(
            inquiry=inquiry,
            action="RESPONDED",
            actor_employee=actor_employee,
            request=request,
            before_data=before_data,
            note=plain_content[:500],
        )
    else:
        _touch_inquiry(inquiry)
        from .handling_time import handle_time_event
        handle_time_event(inquiry.pk, 'FOLLOW_UP', key=f'FOLLOW_UP:{communication.pk}')
    return inquiry, communication


@transaction.atomic
def attach_inquiry_contact(*, inquiry, customer_contact, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    if inquiry.customer_contact_id is not None:
        raise InquiryStateConflict("当前询盘已经有关联联系人，补充入口不能用于替换联系人。")
    if inquiry.status in {InquiryStatus.CONVERTED, InquiryStatus.CLOSED, InquiryStatus.CANCELLED}:
        raise InquiryStateConflict("终态询盘不能再补充联系人。")
    if customer_contact.customer_account_id != inquiry.customer_account_id:
        raise ValidationError({"customer_contact_id": "联系人必须属于当前询盘客户。"})
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    inquiry.customer_contact = customer_contact
    inquiry.save(update_fields=["customer_contact", "updated_at"])
    _write_inquiry_records(
        inquiry=inquiry,
        action="CONTACT_ATTACHED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=f"补充联系人：{customer_contact.display_name}",
    )
    return inquiry


@transaction.atomic
def mark_inquiry_quote_accepted(*, inquiry, actor_employee, request, note=""):
    """由报价接受事务调用，询盘不自行伪造报价接受事实。"""
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    if inquiry.status in {InquiryStatus.QUOTE_ACCEPTED, InquiryStatus.CONVERTED}:
        return inquiry
    if inquiry.status in {
        InquiryStatus.LOST,
        InquiryStatus.CLOSED,
        InquiryStatus.CANCELLED,
    }:
        raise InquiryStateConflict("当前询盘状态不能记录客户接受报价。")
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    inquiry.status = InquiryStatus.QUOTE_ACCEPTED
    inquiry.save(update_fields=["status", "updated_at"])
    from .handling_time import has_sales_order, has_submitted_sample
    now = timezone.now()
    _finish_sla(inquiry, SlaTrackingStatus.MET, now)
    if not has_sales_order(inquiry):
        _start_sla(inquiry, now, 'SAMPLE_FOLLOW_UP' if has_submitted_sample(inquiry) else 'POST_ACCEPTANCE')
    _write_inquiry_records(
        inquiry=inquiry,
        action="QUOTE_ACCEPTED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note or "客户已接受正式报价版本。",
    )
    return inquiry


@transaction.atomic
def set_inquiry_priority(*, inquiry, priority, actor_employee, request):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    require_matching_etag(request, inquiry)
    if priority not in ["", *InquiryPriority.values]:
        raise ValidationError({"priority": "优先级必须为高、中、低或未设置。"})
    if inquiry.archived_at is not None:
        raise Conflict("已归档询盘不能设置优先级。")
    if inquiry.priority == priority:
        return inquiry
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    inquiry.priority = priority
    inquiry.save(update_fields=["priority", "updated_at"])
    label = inquiry.get_priority_display() or "未设置"
    _write_inquiry_records(
        inquiry=inquiry, action="PRIORITY_CHANGED", actor_employee=actor_employee,
        request=request, before_data=before_data, note=f"人工设置优先级为：{label}",
    )
    return inquiry


@transaction.atomic
def assign_inquiry(*, inquiry, owner_employee, reason, actor_employee, request, expected_etag=None):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    if expected_etag is None:
        require_matching_etag(request, inquiry)
    else:
        from apps.core.api.concurrency import etag_for_instance
        if expected_etag != etag_for_instance(inquiry):
            from apps.core.api.concurrency import PreconditionFailed
            raise PreconditionFailed()
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    previous_owner = inquiry.owner_employee
    now = timezone.now()
    inquiry.owner_employee = owner_employee
    inquiry.assigned_at = now
    inquiry.save(update_fields=["owner_employee", "assigned_at", "updated_at"])
    if owner_employee:
        _finish_sla(inquiry, SlaTrackingStatus.MET, now, 'ASSIGNMENT')
    InquiryAssignmentHistory.objects.create(
        inquiry=inquiry,
        previous_owner_employee=previous_owner,
        new_owner_employee=owner_employee,
        assigned_by_employee=actor_employee,
        assignment_reason=reason,
        assigned_at=now,
    )
    _write_inquiry_records(inquiry=inquiry, action="ASSIGNED", actor_employee=actor_employee, request=request, before_data=before_data, note=reason)
    return inquiry


@transaction.atomic
def mark_inquiry_invalid(*, inquiry, reason_code, reason_detail="", actor_employee, request, expected_etag=None):
    inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
    if expected_etag is None:
        require_matching_etag(request, inquiry)
    else:
        from apps.core.api.concurrency import etag_for_instance
        if expected_etag != etag_for_instance(inquiry):
            from apps.core.api.concurrency import PreconditionFailed
            raise PreconditionFailed()
    if inquiry.status in {InquiryStatus.CONVERTED, InquiryStatus.CLOSED, InquiryStatus.CANCELLED}:
        raise Conflict("当前询盘不能标记为无效。")
    before_data = model_snapshot(inquiry, INQUIRY_FIELDS)
    inquiry.status = InquiryStatus.CANCELLED
    inquiry.close_reason_code = reason_code
    inquiry.close_reason_detail = reason_detail
    inquiry.save(update_fields=["status", "close_reason_code", "close_reason_detail", "updated_at"])
    _finish_sla(inquiry, SlaTrackingStatus.CANCELLED, timezone.now())
    _write_inquiry_records(inquiry=inquiry, action="MARKED_INVALID", actor_employee=actor_employee, request=request, before_data=before_data, note=f"{reason_code}: {reason_detail}")
    return inquiry


@transaction.atomic
def link_inquiry_file(*, inquiry, business_file, file_role, actor_employee, request):
    from apps.files.reference_guards import require_non_finance_receipt_file
    require_non_finance_receipt_file(business_file)
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


def upload_inquiry_attachment(*, inquiry, uploaded_file, upload_id, actor_employee, request):
    from pathlib import Path
    from django.conf import settings
    from apps.files.models import BusinessFile
    from .uploads import attachment_hash, save_inquiry_attachment

    business_file = None
    try:
        with transaction.atomic():
            inquiry = Inquiry.objects.select_for_update().get(pk=inquiry.pk)
            _ensure_draft(inquiry)
            existing = inquiry.file_links.select_related("business_file").filter(business_file_id=upload_id).first()
            if existing:
                if existing.business_file.content_hash != attachment_hash(uploaded_file):
                    raise ValidationError("同一上传标识不能用于不同文件。")
                return existing, inquiry
            require_matching_etag(request, inquiry)
            if BusinessFile.objects.filter(pk=upload_id).exists():
                raise ValidationError("上传标识已使用，请重新选择附件。")
            if inquiry.file_links.count() >= 100:
                raise ValidationError("单张询盘最多上传 100 个附件。")
            business_file = save_inquiry_attachment(uploaded_file, actor_employee, inquiry.pk, upload_id)
            return link_inquiry_file(
                inquiry=inquiry, business_file=business_file, file_role="CUSTOMER_ATTACHMENT",
                actor_employee=actor_employee, request=request,
            )
    except Exception:
        if business_file is not None:
            (Path(settings.MEDIA_ROOT) / business_file.storage_key).unlink(missing_ok=True)
        raise
