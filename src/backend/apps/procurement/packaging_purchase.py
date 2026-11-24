import hashlib
from collections import defaultdict

from django.db import transaction
from rest_framework.exceptions import APIException, NotFound, ValidationError

from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, etag_for_instance
from apps.core.api.exceptions import Conflict
from apps.production_tasks.models import ProductionTask

from .group_selectors import purchase_groups_with_context
from .group_services import _confirm_orders_with_default_sheets, create_purchase_batch, create_purchase_group
from .models import PurchaseGroup, PurchaseGroupLine, PurchaseOrder, PurchaseOrderStatus, PurchaseScope
from .tracking_hooks import defer_supplier_tracking, refresh_tracking_after_commit


def _with_task_number(error, task_number):
    detail = error.detail
    if isinstance(detail, dict):
        error.detail = {**detail, "production_task_number": [task_number]}
    else:
        error.detail = f"生产任务 {task_number}：{detail}"
    return error


@transaction.atomic
@defer_supplier_tracking()
def prepare_packaging_groups(sources, allowed_tasks, request):
    by_task = defaultdict(list)
    for source in sources:
        by_task[source["production_task_id"]].append(source)
    tasks = list(allowed_tasks.filter(pk__in=by_task).order_by("pk").values_list("pk", "task_number"))
    if len(tasks) != len(by_task):
        raise NotFound("所选生产任务不存在或不在当前账号的跟进范围内。")
    list(ProductionTask.objects.filter(pk__in=by_task).order_by("pk").select_for_update())
    task_ids = allowed_tasks.values_list("pk", flat=True)
    group_ids = []
    for task_id, task_number in tasks:
        try:
            group = create_purchase_group(
                validated_data={"production_task_id": task_id, "sources": by_task[task_id]},
                allowed_task_ids=task_ids, actor_employee=request.employee, request=request,
                purchase_scope=PurchaseScope.PACKAGING,
            )
        except APIException as error:
            raise _with_task_number(error, task_number)
        group_ids.append(group.pk)
    refresh_tracking_after_commit(by_task)
    return purchase_groups_with_context(PurchaseGroup.objects.filter(pk__in=group_ids)).order_by(
        "production_task_number_snapshot", "pk",
    )


def packaging_page_etag(groups):
    versions = "".join(sorted(etag_for_instance(group) for group in groups))
    return f'"{hashlib.sha256(versions.encode()).hexdigest()}"'


def get_packaging_page(allowed_groups, group_ids, batch_session_id):
    session = PurchaseOrder.objects.filter(batch_session_id=batch_session_id)
    if group_ids is None:
        group_ids = list(session.order_by().values_list("purchase_group_id", flat=True).distinct())
        if not group_ids:
            raise NotFound("没有可继续办理的包材采购批次。")
    groups = list(purchase_groups_with_context(allowed_groups.filter(pk__in=group_ids)).order_by(
        "production_task_number_snapshot", "pk",
    ))
    if len(groups) != len(group_ids):
        raise NotFound("所选包材采购需求不存在或不在当前账号的跟进范围内。")
    if session.exclude(purchase_group_id__in=group_ids).exists():
        raise Conflict("本批包含其他采购需求，请返回原填写页面继续办理。")
    return groups


@transaction.atomic
@defer_supplier_tracking()
def process_packaging_page(*, allowed_groups, allowed_task_ids, data, request, confirm):
    group_ids = data["group_ids"]
    session_id = data["batch_session_id"]
    batch = data.get("batch")
    task_ids = allowed_groups.filter(pk__in=group_ids).order_by().values("production_task_id")
    list(ProductionTask.objects.filter(pk__in=task_ids).order_by("pk").select_for_update())
    groups = list(allowed_groups.filter(pk__in=group_ids).order_by("pk").select_for_update())
    if len(groups) != len(group_ids):
        raise NotFound("所选包材采购需求不存在或不在当前账号的跟进范围内。")
    session = PurchaseOrder.objects.filter(batch_session_id=session_id)
    if session.exclude(purchase_group_id__in=group_ids).exists():
        raise Conflict("本批包含其他采购需求，请返回原填写页面继续办理。")
    orders = session.filter(archived_at__isnull=True)
    drafts = orders.filter(status=PurchaseOrderStatus.DRAFT)
    already_confirmed = orders.exclude(status=PurchaseOrderStatus.DRAFT).exists()
    rows_by_group = defaultdict(list)
    if batch:
        rows = batch["lines"]
        line_groups = dict(PurchaseGroupLine.objects.filter(
            purchase_group_id__in=group_ids,
            pk__in=[row["purchase_group_line_id"] for row in rows],
        ).values_list("pk", "purchase_group_id"))
        for row in rows:
            group_id = line_groups.get(row["purchase_group_line_id"])
            if group_id is None:
                raise ValidationError({"lines": "采购明细必须属于本页选中的包材采购需求。"})
            rows_by_group[group_id].append(row)
    repeated = bool(batch) and set(rows_by_group) == set(orders.filter(
        batch_request_id=batch["request_id"],
    ).values_list("purchase_group_id", flat=True))
    expected = request.headers.get("If-Match")
    if not expected:
        raise PreconditionRequired()
    if not repeated and not (confirm and already_confirmed and not batch and not drafts.exists()):
        if expected != packaging_page_etag(groups):
            raise PreconditionFailed()
        if already_confirmed:
            raise Conflict("本批已确认，请从采购需求重新新增批次。")
    confirmed_tasks = []
    for group in groups:
        rows = rows_by_group[group.pk]
        if rows:
            try:
                create_purchase_batch(
                    group_id=group.pk,
                    validated_data={**batch, "lines": rows, "batch_session_id": session_id},
                    allowed_task_ids=allowed_task_ids, actor_employee=request.employee, request=request,
                    group_version_checked=True,
                )
            except APIException as error:
                raise _with_task_number(error, group.production_task_number_snapshot)
        if confirm:
            pending = list(drafts.filter(purchase_group=group).order_by("pk").values_list("pk", flat=True))
            if pending:
                try:
                    _confirm_orders_with_default_sheets(pending, allowed_task_ids, request.employee, request)
                except APIException as error:
                    raise _with_task_number(error, group.production_task_number_snapshot)
                group.save(update_fields=["updated_at"])
                confirmed_tasks.append(group.production_task_id)
    if confirm and not orders.exclude(status=PurchaseOrderStatus.DRAFT).exists():
        raise Conflict("本批暂无待确认采购。")
    refresh_tracking_after_commit(confirmed_tasks)
    return get_packaging_page(allowed_groups, group_ids, session_id)
