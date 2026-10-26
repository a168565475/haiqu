import hashlib
import json

from django.db import IntegrityError, transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from .cost_models import ProductionTaskExpense
from .models import ProductionTask


FIELDS = ('expense_type', 'description', 'amount', 'occurred_on', 'remark')


def _snapshot(expense):
    return {field: str(getattr(expense, field)) for field in (*FIELDS, 'production_task_id', 'voided_at')}


def _lock_task(task):
    task = ProductionTask.objects.select_for_update().get(pk=task.pk)
    if task.archived_at is not None:
        raise Conflict('已归档生产任务不能维护费用。')
    return task


def _audit(expense, *, action, actor_employee, request, before=None):
    write_audit_log(object_type='PRODUCTION_TASK_EXPENSE', object_id=expense.pk,
                    context_type='PRODUCTION_TASK', context_id=expense.production_task_id,
                    action=action, actor_employee=actor_employee, request=request,
                    before_data=before, after_data=_snapshot(expense))


def _replay(expense, task, payload_hash):
    if expense.production_task_id != task.pk or expense.request_payload_hash != payload_hash:
        raise Conflict('创建请求编号已用于其他任务或不同费用内容。')
    if expense.voided_at is not None:
        raise Conflict('该请求创建的费用已作废，不能重新创建。')
    return expense, False


@transaction.atomic
def create_task_expense(*, task, validated_data, actor_employee, request):
    task = _lock_task(task)
    data = dict(validated_data)
    data.setdefault('remark', '')
    request_id = data.pop('client_request_id')
    # 固定原始请求摘要，后续编辑费用也不改变创建重试的识别依据。
    payload_hash = hashlib.sha256(json.dumps({field: str(data[field]) for field in FIELDS}, sort_keys=True).encode()).hexdigest()
    existing = ProductionTaskExpense.objects.filter(client_request_id=request_id).first()
    if existing:
        return _replay(existing, task, payload_hash)
    try:
        with transaction.atomic():
            expense = ProductionTaskExpense.objects.create(production_task=task, **data, client_request_id=request_id,
                request_payload_hash=payload_hash, created_by_employee=actor_employee, updated_by_employee=actor_employee)
    except IntegrityError:
        existing = ProductionTaskExpense.objects.filter(client_request_id=request_id).first()
        if existing is None:
            raise
        return _replay(existing, task, payload_hash)
    _audit(expense, action='CREATED', actor_employee=actor_employee, request=request)
    return expense, True


@transaction.atomic
def update_task_expense(*, task, expense_id, validated_data, actor_employee, request):
    task = _lock_task(task)
    expense = get_object_or_404(ProductionTaskExpense.objects.select_for_update(), pk=expense_id, production_task=task, voided_at__isnull=True)
    require_matching_etag(request, expense)
    before = _snapshot(expense)
    for field, value in validated_data.items():
        setattr(expense, field, value)
    expense.updated_by_employee = actor_employee
    expense.save(update_fields=[*validated_data, 'updated_by_employee', 'updated_at'])
    _audit(expense, action='UPDATED', actor_employee=actor_employee, request=request, before=before)
    return expense


@transaction.atomic
def void_task_expense(*, task, expense_id, actor_employee, request):
    task = _lock_task(task)
    expense = get_object_or_404(ProductionTaskExpense.objects.select_for_update(), pk=expense_id, production_task=task, voided_at__isnull=True)
    require_matching_etag(request, expense)
    before = _snapshot(expense)
    expense.voided_at = timezone.now()
    expense.updated_by_employee = actor_employee
    expense.save(update_fields=['voided_at', 'updated_by_employee', 'updated_at'])
    _audit(expense, action='VOIDED', actor_employee=actor_employee, request=request, before=before)
