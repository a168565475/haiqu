from apps.access_control import sales_policy
from django.core.exceptions import ObjectDoesNotExist
import json
from datetime import timedelta

from django.core.serializers.json import DjangoJSONEncoder
from django.db import connection, transaction
from django.db.models import F
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

from .models import (
    ApprovalRequest,
    ApprovalStatus,
    BusinessTask,
    TaskBatchOperation,
    TaskChecklistItem,
    TaskEvent,
    TaskOriginType,
    TaskReminder,
    TaskReminderStatus,
    TaskStatus,
    TaskWorkState,
)


TASK_FIELDS = [
    "assignee_employee",
    "created_by_employee",
    "title",
    "description",
    "status",
    "priority",
    "task_number",
    "task_type",
    "origin_type",
    "origin_code",
    "contact",
    "work_state",
    "work_state_reason",
    "next_check_at",
    "due_at",
    "completed_at",
    "completion_result",
    "cancelled_at",
    "cancel_reason",
    "reschedule_count",
    "business_version",
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
    for source_type, relation_name, prefetched_name, object_field, customer_path in [
        ("CUSTOMER", "customer_links", "primary_customer_links", "customer_account", "self"),
        ("COMMUNICATION", "communication_links", "primary_communication_links", "communication", "customer_account"),
        ("INQUIRY", "inquiry_links", "primary_inquiry_links", "inquiry", "customer_account"),
        (
            "QUOTATION_VERSION",
            "quotation_links",
            "primary_quotation_links",
            "quotation_version",
            "quotation.customer_account",
        ),
        ("SAMPLE_REQUEST", "sample_links", "primary_sample_links", "sample_request", "customer_account"),
    ]:
        prefetched_links = getattr(task, prefetched_name, None)
        link = prefetched_links[0] if prefetched_links else getattr(task, relation_name).filter(is_primary_source=True).first()
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
    TaskEvent.objects.create(
        business_task=task,
        event_type=action,
        actor_employee=actor_employee,
        note=note,
        before_data=_json_data(before_data or {}),
        after_data=_json_data({
            **model_snapshot(task, TASK_FIELDS),
            "source_type": source_type,
            "source_id": str(source_id) if source_id else None,
        }),
    )


def _json_data(value):
    return json.loads(json.dumps(value, cls=DjangoJSONEncoder))


def generate_task_number():
    """只使用 workflow 自己的序列，避免干扰其他业务编号。"""

    with connection.cursor() as cursor:
        cursor.execute("SELECT nextval('workflow_task_number_seq')")
        number = cursor.fetchone()[0]
    return f"TASK-{timezone.localtime().year}-{number:04d}"


def _validate_contact_customer(contact, customer):
    if contact is not None and customer is not None and contact.customer_account_id != customer.pk:
        raise ValidationError({"contact_id": ["联系人必须属于任务来源客户。"]})


def _save_task(task, update_fields):
    task.business_version = F("business_version") + 1
    task.save(update_fields=[*update_fields, "business_version", "updated_at"])
    task.refresh_from_db()


def _close_scheduled_reminders(task, reason):
    now = timezone.now()
    return TaskReminder.objects.filter(
        business_task=task,
        status=TaskReminderStatus.SCHEDULED,
    ).update(status=TaskReminderStatus.CLOSED, closed_at=now, close_reason=reason, updated_at=now)


@transaction.atomic
def create_task(*, validated_data, actor_employee, request, resolved_source=None):
    from apps.access_control import module_policy
    if module_policy.enabled():
        sales_policy.require_owner(request, 'workflow.add_businesstask', validated_data.get('assignee_employee'))
    source_type = validated_data.pop("source_type", None)
    validated_data.pop("source_id", None)
    checklist = validated_data.pop("checklist", [])
    reminder_at_list = validated_data.pop("reminder_at_list", [])
    contact = validated_data.get("contact")
    if resolved_source:
        _validate_contact_customer(contact, resolved_source[1])
    task = BusinessTask.objects.create(
        created_by_employee=actor_employee,
        task_number=generate_task_number(),
        **validated_data,
    )
    if resolved_source:
        source, _, link_model, link_field = resolved_source
        link_model.objects.create(
            business_task=task,
            is_primary_source=True,
            **{link_field: source},
        )
    TaskChecklistItem.objects.bulk_create(
        [
            TaskChecklistItem(business_task=task, content=content, sort_order=index)
            for index, content in enumerate(checklist)
            if content.strip()
        ]
    )
    TaskReminder.objects.bulk_create(
        [TaskReminder(business_task=task, remind_at=remind_at) for remind_at in reminder_at_list]
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
    if "contact" in validated_data:
        customer, _, _ = task_customer_and_source(task)
        _validate_contact_customer(validated_data["contact"], customer)
    _save_task(task, list(validated_data.keys()))
    _write_task_records(
        task=task,
        action="UPDATED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
    )
    return task


@transaction.atomic
def transition_task(*, task, action, note, actor_employee, request, enforce_etag=True):
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    if enforce_etag:
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
        task.completed_at = timezone.now()
        task.completion_result = note
        _close_scheduled_reminders(task, "任务已完成")
    if target_status == "CANCELLED":
        task.cancelled_at = timezone.now()
        task.cancel_reason = note
        _close_scheduled_reminders(task, "任务已取消")
    _save_task(task, ["status", "completed_at", "completion_result", "cancelled_at", "cancel_reason"])
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
    from apps.access_control import module_policy
    if module_policy.enabled():
        sales_policy.require_owner(request, 'workflow.reassign_businesstask', assignee_employee)
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status not in {"PENDING", "IN_PROGRESS"}:
        raise Conflict("终态任务不能转派。")
    if task.assignee_employee_id == assignee_employee.pk:
        raise ValidationError({"assignee_employee_id": ["新负责人不能与当前负责人相同。"]})
    before_data = model_snapshot(task, TASK_FIELDS)
    task.assignee_employee = assignee_employee
    _save_task(task, ["assignee_employee"])
    _write_task_records(
        task=task,
        action="REASSIGNED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=reason,
    )
    return task


@transaction.atomic
def set_task_work_state(*, task, work_state, reason, next_check_at, actor_employee, request):
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status not in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}:
        raise Conflict("终态任务不能修改工作状态。")
    if work_state in {TaskWorkState.WAITING_CUSTOMER, TaskWorkState.BLOCKED} and not reason:
        raise ValidationError({"reason": ["请填写原因。"]})
    before_data = model_snapshot(task, TASK_FIELDS)
    task.work_state = work_state
    task.work_state_reason = reason if work_state != TaskWorkState.NORMAL else ""
    task.next_check_at = next_check_at if work_state == TaskWorkState.WAITING_CUSTOMER else None
    _save_task(task, ["work_state", "work_state_reason", "next_check_at"])
    _write_task_records(
        task=task,
        action=f"WORK_STATE_{work_state}",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=reason,
    )
    return task


def reschedule_conflicts(task, new_due_at):
    local_due = timezone.localtime(new_due_at)
    hour_start = local_due.replace(minute=0, second=0, microsecond=0)
    hour_end = hour_start + timedelta(hours=1)
    return BusinessTask.objects.filter(
        assignee_employee_id=task.assignee_employee_id,
        status__in=[TaskStatus.PENDING, TaskStatus.IN_PROGRESS],
        priority__in=["HIGH", "URGENT"],
        due_at__gte=hour_start,
        due_at__lt=hour_end,
        archived_at__isnull=True,
    ).exclude(pk=task.pk).order_by("due_at", "id")


@transaction.atomic
def reschedule_task(*, task, new_due_at, reason, sync_reminders, actor_employee, request):
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    if task.status not in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}:
        raise Conflict("终态任务不能改期。")
    if task.due_at is None:
        raise Conflict("没有截止时间的任务不能改期。")
    if new_due_at == task.due_at:
        raise ValidationError({"new_due_at": ["新截止时间不能与原时间相同。"]})
    before_data = model_snapshot(task, TASK_FIELDS)
    reminder_count = 0
    if sync_reminders:
        delta = new_due_at - task.due_at
        reminder_count = TaskReminder.objects.filter(
            business_task=task,
            status=TaskReminderStatus.SCHEDULED,
        ).update(remind_at=F("remind_at") + delta, updated_at=timezone.now())
    task.due_at = new_due_at
    task.reschedule_count += 1
    _save_task(task, ["due_at", "reschedule_count"])
    _write_task_records(
        task=task,
        action="RESCHEDULED",
        actor_employee=actor_employee,
        request=request,
        before_data=before_data,
        note=reason,
    )
    return task, reminder_count


@transaction.atomic
def toggle_checklist_item(*, task, item, is_completed, actor_employee, request):
    task = BusinessTask.objects.select_for_update().get(pk=task.pk)
    require_matching_etag(request, task)
    item = TaskChecklistItem.objects.select_for_update().get(pk=item.pk, business_task=task)
    if task.status not in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}:
        raise Conflict("终态任务不能修改检查清单。")
    item.is_completed = is_completed
    item.completed_at = timezone.now() if is_completed else None
    item.completed_by_employee = actor_employee if is_completed else None
    item.save(update_fields=["is_completed", "completed_at", "completed_by_employee", "updated_at"])
    _save_task(task, [])
    _write_task_records(
        task=task,
        action="CHECKLIST_COMPLETED" if is_completed else "CHECKLIST_REOPENED",
        actor_employee=actor_employee,
        request=request,
        note=item.content,
    )
    return task, item


@transaction.atomic
def execute_batch(*, action, items, event_id, actor_employee, request, assignee_employee=None, reason=""):
    from apps.access_control import module_policy
    if module_policy.enabled():
        from .selectors import accessible_tasks
        permission = 'access_control.complete_businesstask' if action == 'COMPLETE' else 'workflow.reassign_businesstask'
        ids = [item['id'] for item in items]
        if accessible_tasks(request, 'ANY_ACCESS', permission=permission).filter(pk__in=ids).count() != len(ids):
            raise PermissionDenied('批量操作包含未获该操作授权的任务。')
        if action == 'REASSIGN':
            sales_policy.require_owner(request, permission, assignee_employee)
    existing = TaskBatchOperation.objects.filter(event_id=event_id).first()
    if existing:
        if module_policy.enabled() and (existing.actor_employee_id != actor_employee.pk or existing.action != action):
            raise PermissionDenied('该批量操作标识属于其他操作或员工。')
        if module_policy.enabled() and existing.request_data.get('items') != [{'id': str(item['id']), 'version': item['version']} for item in items]:
            raise Conflict('该批量操作标识已经用于其他任务，请刷新后重试。')
        return existing.result_data, True
    if len(items) > 100:
        raise ValidationError({"items": ["单次最多处理 100 条任务。"]})
    ids = [item["id"] for item in items]
    if len(set(ids)) != len(ids):
        raise ValidationError({"items": ["任务不能重复提交。"]})
    tasks = {task.pk: task for task in BusinessTask.objects.select_for_update().filter(pk__in=ids)}
    if len(tasks) != len(ids):
        raise ValidationError({"items": ["存在不可访问或已删除的任务。"]})
    operation = TaskBatchOperation.objects.create(
        event_id=event_id,
        action=action,
        actor_employee=actor_employee,
        request_data={"items": [{"id": str(item["id"]), "version": item["version"]} for item in items]},
    )
    now = timezone.now()
    result_tasks = []
    for item in items:
        task = tasks[item["id"]]
        if task.business_version != item["version"]:
            raise Conflict("部分任务已被修改，请刷新后重试。")
        if task.status not in {TaskStatus.PENDING, TaskStatus.IN_PROGRESS}:
            raise Conflict("批量操作包含终态任务。")
        before_data = model_snapshot(task, TASK_FIELDS)
        if action == "COMPLETE":
            task.status = TaskStatus.COMPLETED
            task.completed_at = now
            task.completion_result = reason
            _close_scheduled_reminders(task, "任务已完成")
        else:
            task.assignee_employee = assignee_employee
        _save_task(task, ["status", "completed_at", "completion_result"] if action == "COMPLETE" else ["assignee_employee"])
        _write_task_records(
            task=task,
            action=f"BULK_{action}",
            actor_employee=actor_employee,
            request=request,
            before_data=before_data,
            note=reason,
        )
        event = TaskEvent.objects.filter(
            business_task=task,
            event_type=f"BULK_{action}",
            batch_operation__isnull=True,
        ).order_by("-created_at").first()
        if event:
            event.batch_operation = operation
            event.save(update_fields=["batch_operation"])
        result_tasks.append(str(task.pk))
    result = {"event_id": str(event_id), "action": action, "task_ids": result_tasks, "count": len(result_tasks)}
    operation.result_data = result
    operation.save(update_fields=["result_data", "updated_at"])
    return result, False


def _approval_context(approval):
    try:
        link = approval.quotation_link
    except ObjectDoesNotExist:
        return None, None
    return link.quotation_version.quotation.customer_account, link.quotation_version


@transaction.atomic
def decide_approval(*, approval, target_status, note, actor_employee, request):
    approval = ApprovalRequest.objects.select_for_update().get(pk=approval.pk)
    from apps.access_control import module_policy
    if module_policy.enabled() and approval.approval_type == 'SAMPLE_FEE_WAIVER':
        raise PermissionDenied('样品费用豁免须通过样品费用审批入口处理。')
    customer, version = _approval_context(approval)
    if customer and target_status != ApprovalStatus.CANCELLED:
        sales_policy.require_customer(request, "quotations.approve_quotation", customer)
    require_matching_etag(request, approval)
    if approval.status != ApprovalStatus.PENDING:
        raise Conflict("审批已经处理，不能重复决定。")
    actor_id = getattr(actor_employee, "pk", None)
    if target_status == ApprovalStatus.CANCELLED:
        if approval.requested_by_employee_id != actor_id:
            raise PermissionDenied("只有审批申请人可以取消该审批。")
    elif approval.current_approver_employee_id != actor_id:
        raise PermissionDenied("只有当前审批人可以处理该审批。")
    if target_status != ApprovalStatus.CANCELLED and version is not None:
        from apps.access_control.module_policy import prohibit_self_approval
        prohibit_self_approval(actor_employee, approval.requested_by_employee_id)
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
    from apps.access_control import module_policy
    if module_policy.enabled() and approval.approval_type == 'SAMPLE_FEE_WAIVER':
        raise PermissionDenied('请在样品中重新提交费用决策，以同时更新费用与审批。')
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
