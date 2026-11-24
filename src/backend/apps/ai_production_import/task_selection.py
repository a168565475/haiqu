"""同一识别记录中的任务逐个处理；历史单任务记录继续使用 main。"""

from django.db import transaction
from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.core.api.concurrency import require_matching_etag
from apps.core.api.exceptions import Conflict

from .models import AiImportState, AiProductionImport


def result_tasks(result):
    if not isinstance(result, dict) or not result:
        return {}
    tasks = {"main": result}
    for item in result.get("additional_tasks", []):
        key = item.get("task_key") if isinstance(item, dict) else None
        if not isinstance(key, str) or not key.strip() or key in tasks:
            raise ValidationError({"task_key": "识别任务编号无效或重复，请重新核对识别结果。"})
        tasks[key] = item
    return tasks


def active_task_key(record):
    return record.source.get("active_task_key", "main")


def active_result(record):
    return result_tasks(record.result).get(active_task_key(record), {})


def has_created_tasks(record):
    return bool(record.task_id or any(
        item.get("task_id") for item in record.source.get("task_states", {}).values()
    ))


def require_task_key(record, task_key):
    expected = active_task_key(record)
    if task_key is None and len(result_tasks(record.result)) == 1:
        return
    if task_key != expected:
        raise Conflict("当前处理任务已变化，请刷新后重新提交，避免写入其他任务。")


def current_task_state(record):
    return {
        "state": record.state,
        "task_id": str(record.task_id) if record.task_id else None,
        "task_number": record.task_number,
        "bom_id": str(record.bom_id) if record.bom_id else None,
        "bom_ids": record.bom_ids or [],
        "review_draft": record.source.get("review_draft"),
        "created_product_keys": record.source.get("created_product_keys", {}),
    }


def task_choices(record):
    states = {**record.source.get("task_states", {}), active_task_key(record): current_task_state(record)}
    choices = []
    for key, result in result_tasks(record.result).items():
        value = result.get("task", {}).get("task_number", {})
        number = value.get("value") if isinstance(value, dict) else value
        state = states.get(key, {})
        choices.append({"task_key": key, "task_number": str(number or "待确认任务号"),
                        "state": state.get("state", AiImportState.REVIEW), "task_id": state.get("task_id")})
    return choices


@transaction.atomic
def select_task(*, employee, record_id, task_key, request):
    from .services import _mapping_active

    record = get_object_or_404(AiProductionImport.objects.select_for_update(), owner=employee, pk=record_id)
    require_matching_etag(request, record)
    if _mapping_active(record) or not record.result:
        raise Conflict("识别完成后才能选择任务。")
    if task_key not in result_tasks(record.result):
        raise ValidationError({"task_key": "该任务不属于当前识别记录。"})
    if task_key == active_task_key(record):
        return record
    states = {**record.source.get("task_states", {}), active_task_key(record): current_task_state(record)}
    selected = states.get(task_key, {})
    record.source = {**record.source, "task_states": states, "active_task_key": task_key,
                     "review_draft": selected.get("review_draft"),
                     "created_product_keys": selected.get("created_product_keys", {})}
    record.state = selected.get("state", AiImportState.REVIEW)
    record.task_id = selected.get("task_id")
    record.task_number = selected.get("task_number", "")
    record.bom_id = selected.get("bom_id")
    record.bom_ids = selected.get("bom_ids", [])
    record.save(update_fields=["source", "state", "task_id", "task_number", "bom_id", "bom_ids", "updated_at"])
    return record
