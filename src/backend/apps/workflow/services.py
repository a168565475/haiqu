from django.core.exceptions import ObjectDoesNotExist
from django.db import transaction
from django.utils import timezone
from rest_framework.exceptions import NotFound, PermissionDenied, ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.crm.models import CommunicationTaskLink, CustomerCommunication
from apps.customers.models import CustomerAccount, CustomerTaskLink
from apps.customers.services import model_snapshot, write_customer_timeline
from apps.inquiries.models import Inquiry, InquiryTaskLink
from apps.quotations.models import QuotationVersion, QuotationVersionTaskLink
from apps.samples.models import SampleRequest, SampleTaskLink

from .models import ApprovalRequest, ApprovalStatus, BusinessTask


TASK_FIELDS = [
    "assignee_employee",
    "created_by_employee",
    "title",
    "description",
    "status",
    "priority",
    "due_at",
    "completed_at",
]


SOURCE_CONFIG = {
    "CUSTOMER": (CustomerAccount, "self", CustomerTaskLink, "customer_account"),
    "COMMUNICATION": (
        CustomerCommunication,
        "customer_account",
        CommunicationTaskLink,
        "communication",
    ),
    "INQUIRY": (Inquiry, "customer_account", InquiryTaskLink, "inquiry"),
    "QUOTATION_VERSION": (
        QuotationVersion,
        "quotation.customer_account",
        QuotationVersionTaskLink,
        "quotation_version",
    ),
    "SAMPLE_REQUEST": (
        SampleRequest,
        "customer_account",
        SampleTaskLink,
        "sample_request",
    ),
}


def _attribute_path(instance, path):
    if path == "self":
        return instance
    value = instance
    for name in path.split("."):
        value = getattr(value, name)
    return value


def resolve_task_source(source_type, source_id):
    try:
        model, customer_path, link_model, link_field = SOURCE_CONFIG[source_type]
    except KeyError as exc:
        raise ValidationError({"source_type": ["不支持的任务来源类型。"]}) from exc
    try:
        source = model.objects.get(pk=source_id)
    except model.DoesNotExist as exc:
        raise NotFound("任务来源不存在。") from exc
    customer = _attribute_path(source, customer_path)
    return source, customer, link_model, link_field


def validate_task_source_active(source_type, source, customer):
    if customer.archived_at is not None:
        raise Conflict("已归档客户不能新增任务。")
    if getattr(source, "archived_at", None) is not None:
        raise Conflict("已归档业务记录不能新增任务。")
    if source_type == "QUOTATION_VERSION" and source.quotation.archived_at is not None:
        raise Conflict("已归档报价不能新增任务。")


def task_customer_and_source(task):
    for source_type, relation_name, object_field, customer_path in [
        ("CUSTOMER", "customer_links", "customer_account", "self"),
        ("COMMUNICATION", "communication_links", "communication", "customer_account"),
        ("INQUIRY", "inquiry_links", "inquiry", "customer_account"),
        (
            "QUOTATION_VERSION",
            "quotation_links",
            "quotation_version",
            "quotation.customer_account",
        ),
        ("SAMPLE_REQUEST", "sample_links", "sample_request", "customer_account"),
    ]:
        link = getattr(task, relation_name).filter(is_primary_source=True).first()
        if link:
            source = getattr(link, object_field)
            return _attribute_path(source, customer_path), source_type, source.pk
    return None, None, None


def _write_task_records(*, task, action, actor_employee, request, before_data=None, note=""):
    customer, source_type, source_id = task_customer_and_source(task)
    write_audit_log(
        object_type="BUSINESS_TASK",
        object_id=task.pk,
        context_type="CUSTOMER_ACCOUNT" if customer else "",
        context_id=customer.pk if customer else None,
        action=action,
        actor_employee=actor_employee,
        before_data=before_data,
        after_data={
            **model_snapshot(task, TASK_FIELDS),
            "source_type": source_type,
            "source_id": str(source_id) if source_id else None,
            "note": note,
        },
        request=request,
    )
    if customer:
        write_customer_timeline(
            customer=customer,
            event_type=f"TASK_{action}",
            title=task.title,
            summary=note,
            source_type="BUSINESS_TASK",
            source_id=task.pk,
            actor_employee=actor_employee,
        )


@transaction.atomic
def create_task(*, validated_data, actor_employee, request, resolved_source=None):
    source_type = validated_data.pop("source_type", None)
    validated_data.pop("source_id", None)
    task = BusinessTask.objects.create(
        created_by_employee=actor_employee,
        **validated_data,
    )
    if resolved_source:
        source, _, link_model, link_field = resolved_source
        link_model.objects.create(
            business_task=task,
            is_primary_source=True,
            **{link_field: source},
        )
    _write_task_records(
        task=task,
        action="CREATED",
        actor_employee=actor_employee,
        request=request,
        note=f"来源：{source_type}" if source_type else "",
    )
    return task


@transaction.atomic
def update_task(*, task, validated_data, actor_employee, request):
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status not in {"PENDING", "IN_PROGRESS"}:
        raise Conflict("终态任务不能再修改。")
    before_data = model_snapshot(task, TASK_FIELDS)
    for field_name, value in validated_data.items():
        setattr(task, field_name, value)
    task.save(update_fields=[*validated_data.keys(), "updated_at"])
    _write_task_records(
        task=task,
        action="UPDATED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
    )
    return task


@transaction.atomic
def transition_task(*, task, action, note, actor_employee, request):
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    transitions = {
        "STARTED": ({"PENDING"}, "IN_PROGRESS"),
        "COMPLETED": ({"PENDING", "IN_PROGRESS"}, "COMPLETED"),
        "CANCELLED": ({"PENDING", "IN_PROGRESS"}, "CANCELLED"),
    }
    allowed_statuses, target_status = transitions[action]
    if task.status not in allowed_statuses:
        raise Conflict(f"当前任务状态 {task.status} 不允许执行此动作。")
    before_data = model_snapshot(task, TASK_FIELDS)
    task.status = target_status
    if target_status == "COMPLETED":
        from django.utils import timezone

        task.completed_at = timezone.now()
    task.save(update_fields=["status", "completed_at", "updated_at"])
    _write_task_records(
        task=task,
        action=action,
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=note,
    )
    return task


@transaction.atomic
def reassign_task(*, task, assignee_employee, reason, actor_employee, request):
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status not in {"PENDING", "IN_PROGRESS"}:
        raise Conflict("终态任务不能转派。")
    if task.assignee_employee_id == assignee_employee.pk:
        raise ValidationError({"assignee_employee_id": ["新负责人不能与当前负责人相同。"]})
    before_data = model_snapshot(task, TASK_FIELDS)
    task.assignee_employee = assignee_employee
    task.save(update_fields=["assignee_employee", "updated_at"])
    _write_task_records(
        task=task,
        action="REASSIGNED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=reason,
    )
    return task


def _approval_context(approval):
    try:
        link = approval.quotation_link
    except ObjectDoesNotExist:
        return None, None
    return link.quotation_version.quotation.customer_account, link.quotation_version


@transaction.atomic
def decide_approval(*, approval, target_status, note, actor_employee, request):
    approval = ApprovalRequest.objects.select_for_update().get(pk=approval.pk)
    require_matching_etag(request, approval)
    if approval.status != ApprovalStatus.PENDING:
        raise Conflict("审批已经处理，不能重复决定。")
    actor_id = getattr(actor_employee, "pk", None)
    if target_status == ApprovalStatus.CANCELLED:
        if approval.requested_by_employee_id != actor_id:
            raise PermissionDenied("只有审批申请人可以取消该审批。")
    elif approval.current_approver_employee_id != actor_id:
        raise PermissionDenied("只有当前审批人可以处理该审批。")
    before_data = model_snapshot(
        approval,
        [
            "current_approver_employee",
            "requested_by_employee",
            "approval_type",
            "status",
            "request_reason",
            "decision_note",
            "submitted_at",
            "decided_at",
        ],
    )
    approval.status = target_status
    approval.decision_note = note
    approval.decided_at = timezone.now()
    approval.save(update_fields=["status", "decision_note", "decided_at", "updated_at"])
    customer, version = _approval_context(approval)
    if version:
        version.updated_at = timezone.now()
        version.save(update_fields=["updated_at"])
    write_audit_log(
        object_type="APPROVAL_REQUEST",
        object_id=approval.pk,
        context_type="CUSTOMER_ACCOUNT" if customer else "",
        context_id=customer.pk if customer else None,
        action=target_status,
        actor_employee=actor_employee,
        before_data=before_data,
        after_data=model_snapshot(
            approval,
            ["status", "decision_note", "decided_at"],
        ),
        request=request,
    )
    if customer and version:
        write_customer_timeline(
            customer=customer,
            event_type=f"QUOTATION_APPROVAL_{target_status}",
            title=f"{version.quotation.quotation_number} V{version.version_number} 审批{approval.get_status_display()}",
            summary=note,
            source_type="APPROVAL_REQUEST",
            source_id=approval.pk,
            actor_employee=actor_employee,
        )
    return approval, version


@transaction.atomic
def cancel_approval(*, approval, reason, actor_employee, request):
    approval = ApprovalRequest.objects.select_for_update().get(pk=approval.pk)
    require_matching_etag(request, approval)
    if approval.status != ApprovalStatus.PENDING:
        raise Conflict("只有待处理审批可以取消。")
    if approval.requested_by_employee_id != getattr(actor_employee, "pk", None):
        raise PermissionDenied("只有审批申请人可以取消该审批。")
    return decide_approval(
        approval=approval,
        target_status=ApprovalStatus.CANCELLED,
        note=reason,
        actor_employee=actor_employee,
        request=request,
    )
