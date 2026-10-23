import math
from datetime import timedelta

from django.db import transaction
from apps.organizations.selectors import active_department_employees
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.files.uploads import save_scanned_image

from .models import (
    ComplaintStatus,
    CustomerComplaint,
    CustomerComplaintAttachment,
    CustomerComplaintProgress,
)
from .services import model_snapshot, write_customer_timeline


ALLOWED_STATUS_TRANSITIONS = {
    ComplaintStatus.ACCEPTED: {ComplaintStatus.RESPONSIBILITY_CONFIRMATION},
    ComplaintStatus.RESPONSIBILITY_CONFIRMATION: {ComplaintStatus.SOLUTION_PLANNING},
    ComplaintStatus.SOLUTION_PLANNING: {ComplaintStatus.CUSTOMER_CONFIRMATION},
    ComplaintStatus.CUSTOMER_CONFIRMATION: {ComplaintStatus.CLOSED},
    ComplaintStatus.CLOSED: set(),
    ComplaintStatus.CANCELLED: set(),
}


def add_business_days(value, days):
    result = value
    added = 0
    while added < days:
        result += timedelta(days=1)
        if result.weekday() < 5:
            added += 1
    return result


def calculate_complaint_sla(complaint_type_item, severity_item, started_at=None):
    started_at = started_at or timezone.now()
    severity_rules = severity_item.extra_data or {}
    type_rules = complaint_type_item.extra_data or {}
    multiplier = float(type_rules.get("sla_multiplier", 1))
    response_hours = max(1, math.ceil(float(severity_rules.get("first_response_hours", 24)) * multiplier))
    completion_days = max(
        1,
        math.ceil(float(severity_rules.get("resolution_business_days", 5)) * multiplier),
    )
    return {
        "first_response_hours": response_hours,
        "resolution_business_days": completion_days,
        "first_response_due_at": started_at + timedelta(hours=response_hours),
        "target_completion_at": add_business_days(started_at, completion_days),
    }


@transaction.atomic
def create_complaint(*, validated_data, actor_employee, request):
    if actor_employee is None:
        raise ValidationError("当前账号未绑定有效员工，不能创建客诉。")
    collaborators = validated_data.pop("collaborator_employees", [])
    customer = validated_data["customer_account"]
    owner = validated_data.pop("owner_employee", None) or actor_employee
    if not active_department_employees("DEPT_BUSINESS").filter(pk=owner.pk).exists():
        raise ValidationError({"owner_employee_id": "请选择业务部的在职员工。"})
    sla = calculate_complaint_sla(
        validated_data["complaint_type_item"],
        validated_data["severity_item"],
    )
    complaint = CustomerComplaint.objects.create(
        complaint_code=next_business_number("COMPLAINT"),
        original_customer_account=customer,
        owner_employee=owner,
        created_by_employee=actor_employee,
        last_updated_by_employee=actor_employee,
        first_response_due_at=sla["first_response_due_at"],
        target_completion_at=sla["target_completion_at"],
        **validated_data,
    )
    complaint.collaborator_employees.set(collaborators)
    CustomerComplaintProgress.objects.create(
        complaint=complaint,
        from_status=ComplaintStatus.ACCEPTED,
        to_status=ComplaintStatus.ACCEPTED,
        progress_note="客诉已创建并受理。",
        created_by_employee=actor_employee,
    )
    audit_data = {
        "complaint_code": complaint.complaint_code,
        "customer_account_id": complaint.customer_account_id,
        "status": complaint.status,
        "owner_employee_id": complaint.owner_employee_id,
        "first_response_hours": sla["first_response_hours"],
        "resolution_business_days": sla["resolution_business_days"],
    }
    write_audit_log(
        object_type="CUSTOMER_COMPLAINT",
        object_id=complaint.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=customer.pk,
        action="CREATED",
        actor_employee=actor_employee,
        after_data=audit_data,
        request=request,
    )
    write_customer_timeline(
        customer=customer,
        event_type="CUSTOMER_COMPLAINT_CREATED",
        title=f"新建客诉 {complaint.complaint_code}",
        summary=complaint.title,
        source_type="CUSTOMER_COMPLAINT",
        source_id=complaint.pk,
        actor_employee=actor_employee,
        event_data={"status": complaint.status},
    )
    return complaint


@transaction.atomic
def update_complaint(*, complaint, validated_data, actor_employee, request):
    require_matching_etag(request, complaint)
    locked = CustomerComplaint.objects.select_for_update().get(pk=complaint.pk)
    require_matching_etag(request, locked)
    snapshot_fields = [
        "contact",
        "complaint_type_item",
        "severity_item",
        "title",
        "source_order_reference",
        "source_order_snapshot",
        "issue_description",
        "owner_employee",
    ]
    before_data = model_snapshot(locked, snapshot_fields)
    collaborators = validated_data.pop("collaborator_employees", None)
    sla_fields_changed = "complaint_type_item" in validated_data or "severity_item" in validated_data
    for field_name, value in validated_data.items():
        setattr(locked, field_name, value)
    if sla_fields_changed:
        sla = calculate_complaint_sla(locked.complaint_type_item, locked.severity_item, locked.created_at)
        locked.first_response_due_at = sla["first_response_due_at"]
        locked.target_completion_at = sla["target_completion_at"]
    locked.last_updated_by_employee = actor_employee
    locked.full_clean()
    locked.save()
    if collaborators is not None:
        locked.collaborator_employees.set(collaborators)
    write_audit_log(
        object_type="CUSTOMER_COMPLAINT",
        object_id=locked.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=locked.customer_account_id,
        action="UPDATED",
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(locked, snapshot_fields),
        request=request,
    )
    write_customer_timeline(
        customer=locked.customer_account,
        event_type="CUSTOMER_COMPLAINT_UPDATED",
        title=f"更新客诉 {locked.complaint_code}",
        summary=locked.title,
        source_type="CUSTOMER_COMPLAINT",
        source_id=locked.pk,
        actor_employee=actor_employee,
    )
    return locked


@transaction.atomic
def add_complaint_progress(*, complaint, validated_data, actor_employee, request):
    require_matching_etag(request, complaint)
    locked = CustomerComplaint.objects.select_for_update().get(pk=complaint.pk)
    require_matching_etag(request, locked)
    if locked.status in {ComplaintStatus.CLOSED, ComplaintStatus.CANCELLED}:
        raise ValidationError("已关闭或已取消的客诉不能继续更新进展。")
    target_status = validated_data["to_status"]
    if target_status != locked.status:
        allowed = ALLOWED_STATUS_TRANSITIONS[locked.status]
        if target_status == ComplaintStatus.CANCELLED:
            allowed = {*allowed, ComplaintStatus.CANCELLED}
        if target_status not in allowed:
            raise ValidationError(
                {"to_status": f"不能从“{locked.get_status_display()}”直接变更为目标状态。"}
            )
    now = timezone.now()
    previous_status = locked.status
    progress = CustomerComplaintProgress.objects.create(
        complaint=locked,
        from_status=previous_status,
        to_status=target_status,
        progress_note=validated_data["progress_note"],
        root_cause=validated_data.get("root_cause", ""),
        responsibility=validated_data.get("responsibility", ""),
        solution=validated_data.get("solution", ""),
        customer_feedback=validated_data.get("customer_feedback", ""),
        created_by_employee=actor_employee,
    )
    for field_name in ["root_cause", "responsibility", "solution", "customer_feedback"]:
        if field_name in validated_data:
            setattr(locked, field_name, validated_data[field_name])
    locked.status = target_status
    if locked.first_responded_at is None:
        locked.first_responded_at = now
    if target_status == ComplaintStatus.CLOSED:
        locked.completed_at = now
    if target_status == ComplaintStatus.CANCELLED:
        locked.cancelled_at = now
    locked.last_updated_by_employee = actor_employee
    locked.save()
    write_audit_log(
        object_type="CUSTOMER_COMPLAINT",
        object_id=locked.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=locked.customer_account_id,
        action="PROGRESS_UPDATED",
        actor_employee=actor_employee,
        before_data={"status": previous_status},
        after_data={"status": target_status, "progress_entry_id": progress.pk},
        request=request,
    )
    write_customer_timeline(
        customer=locked.customer_account,
        event_type="CUSTOMER_COMPLAINT_PROGRESS_UPDATED",
        title=f"客诉进展：{locked.get_status_display()}",
        summary=progress.progress_note,
        source_type="CUSTOMER_COMPLAINT",
        source_id=locked.pk,
        actor_employee=actor_employee,
        event_data={"from_status": previous_status, "to_status": target_status},
    )
    return locked, progress


@transaction.atomic
def attach_complaint_image(*, complaint, uploaded_file, progress_entry, caption, actor_employee, request):
    if progress_entry is not None and progress_entry.complaint_id != complaint.pk:
        raise ValidationError({"progress_id": "进展记录不属于当前客诉。"})
    business_file = save_scanned_image(
        uploaded_file,
        actor_employee,
        storage_folder="complaint-images",
        field_label="客诉图片",
    )
    attachment = CustomerComplaintAttachment.objects.create(
        complaint=complaint,
        progress_entry=progress_entry,
        business_file=business_file,
        caption=caption,
        uploaded_by_employee=actor_employee,
    )
    complaint.last_updated_by_employee = actor_employee
    complaint.save(update_fields=["last_updated_by_employee", "updated_at"])
    write_audit_log(
        object_type="CUSTOMER_COMPLAINT_ATTACHMENT",
        object_id=attachment.pk,
        context_type="CUSTOMER_ACCOUNT",
        context_id=complaint.customer_account_id,
        action="CREATED",
        actor_employee=actor_employee,
        after_data={
            "complaint_id": complaint.pk,
            "business_file_id": business_file.pk,
            "original_name": business_file.original_name,
        },
        request=request,
    )
    write_customer_timeline(
        customer=complaint.customer_account,
        event_type="CUSTOMER_COMPLAINT_IMAGE_UPLOADED",
        title=f"客诉上传图片 {business_file.original_name}",
        source_type="CUSTOMER_COMPLAINT",
        source_id=complaint.pk,
        actor_employee=actor_employee,
    )
    return attachment
