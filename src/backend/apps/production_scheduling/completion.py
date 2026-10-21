from copy import copy

from django.db import transaction
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied

from apps.access_control import module_policy, sales_policy
from apps.core.api.concurrency import etag_for_instance, require_matching_etag
from apps.core.api.exceptions import Conflict
from apps.core.api.permissions import BusinessActionPermission
from apps.core.audit import write_audit_log
from apps.inventory.assembly_receipts import assembly_progress_for_plans
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct, ProductionTaskStatus
from apps.production_tasks.selectors import accessible_production_tasks
from apps.production_tasks.services import close_production_task
from apps.sales_orders.models import SalesOrder, SalesOrderStatus
from apps.sales_orders.selectors import accessible_sales_orders, sales_order_completion_progress
from apps.sales_orders.services import complete_sales_order
from apps.workshop_reporting.schedule_progress import schedule_progress_statuses

from .models import ProductionSchedule, ScheduleStatus
from .selectors import accessible_production_schedules


def _action_request(request, view, action):
    scoped = copy(request)
    view.action = action
    view.request = scoped
    scoped.parser_context = {**(request.parser_context or {}), "view": view}
    return scoped


def _version_request(request, etag):
    versioned = copy(request)
    # 使用客户端实际读取的版本，不能用服务端刚取到的版本代替并发检查。
    versioned.headers = {**request.headers, "If-Match": etag}
    return versioned


def _authorized_schedule(request, schedule_id):
    from apps.production_tasks.api.views import ProductionTaskViewSet
    from .api.views import ProductionScheduleViewSet

    read_request = _action_request(request, ProductionScheduleViewSet(), "retrieve")
    if not BusinessActionPermission().has_permission(read_request, read_request.parser_context["view"]):
        raise PermissionDenied("当前账号没有查看排产计划的权限。")
    schedule = get_object_or_404(accessible_production_schedules(read_request), pk=schedule_id)
    if not module_policy.has_operation(
        request, "access_control.finish_productiontask", "production_tasks.change_productiontask",
    ):
        raise PermissionDenied("当前账号没有完成生产任务的权限。")
    task_request = _action_request(request, ProductionTaskViewSet(), "finish")
    if not accessible_production_tasks(task_request).filter(pk=schedule.production_task_id).exists():
        raise PermissionDenied("关联生产任务超出当前账号的操作范围。")
    return schedule


def _readable_sales_order(request, task):
    permission = "sales_orders.view_salesorder"
    if not task.sales_order_id or not sales_policy.has_permission(request, permission):
        return None
    return accessible_sales_orders(request, permission=permission).filter(
        pk=task.sales_order_id, archived_at__isnull=True,
    ).first()


def _can_complete_sales_order(request, task):
    permission = "access_control.complete_salesorder"
    return sales_policy.has_permission(request, permission) and accessible_sales_orders(
        request, permission=permission,
    ).filter(pk=task.sales_order_id, archived_at__isnull=True).exists()


def schedule_completion_preview(*, schedule_id, request):
    from .api.serializers import ScheduleProductReadSerializer

    schedule = _authorized_schedule(request, schedule_id)
    task = ProductionTask.objects.get(pk=schedule.production_task_id)
    plans = list(schedule.products.filter(removed_at__isnull=True).select_related(
        "product_line__unit", "unit", "image_file",
    ).prefetch_related("crafts__craft"))
    metrics = assembly_progress_for_plans(plans)
    products = []
    for plan in plans:
        display = ScheduleProductReadSerializer(plan).data["product"]
        quantities = metrics[str(plan.pk)]
        products.append({
            "schedule_product_id": str(plan.pk), "product_name": display.get("product_name", ""),
            "specification": display.get("specification_display", ""), "color": display.get("color_name", ""),
            "material": display.get("material", ""), "required_quantity": quantities["required"],
            "received_quantity": quantities["received"], "unit_name": plan.product_line.unit.unit_name,
        })
    sales = {
        "id": None, "order_number": None, "status": None, "status_display": None,
        "etag": None, "can_sync": False, "reason": "生产任务未关联销售订单。",
    }
    if task.sales_order_id:
        order = _readable_sales_order(request, task)
        if order is None:
            sales["reason"] = "当前账号无关联销售订单查看权限，销售状态不可读取。"
        else:
            can_sync = _can_complete_sales_order(request, task)
            sales.update({
                "id": str(order.pk), "order_number": order.order_number,
                "status": order.status, "status_display": order.get_status_display(),
                "etag": etag_for_instance(order), "can_sync": can_sync,
                "reason": "确认时重新核验销售订单的发货、余款及版本。" if can_sync else "当前账号无关联销售订单完结权限。",
            })
    rows = schedule_progress_statuses([schedule.pk])
    return schedule, {
        "schedule_id": str(schedule.pk), "schedule_number": schedule.schedule_number,
        "schedule_etag": etag_for_instance(schedule),
        "task": {"id": str(task.pk), "task_number": task.task_number, "status": task.status,
                 "status_display": task.get_status_display(), "etag": etag_for_instance(task)},
        "progress": rows[0]["progress"] if rows else {}, "products": products, "sales_order": sales,
    }


def _sync_sales_order(*, task, sales_etag, request, reason):
    hidden_statuses = {"before_status": None, "after_status": None}
    if not task.sales_order_id:
        return {"status": "NOT_APPLICABLE", "reason": "生产任务未关联销售订单。", **hidden_statuses}
    if not _can_complete_sales_order(request, task):
        return {"status": "SKIPPED", "reason": "生产任务已完成；当前账号无关联销售订单完结权限，未同步销售状态。", **hidden_statuses}
    order = SalesOrder.objects.select_for_update().get(pk=task.sales_order_id)
    visible = _readable_sales_order(request, task) is not None
    statuses = {"before_status": order.status, "after_status": order.status} if visible else hidden_statuses
    if order.status == SalesOrderStatus.COMPLETED:
        return {"status": "ALREADY_COMPLETED", "reason": "关联销售订单已经完成。", **statuses}
    if order.status not in {SalesOrderStatus.CONFIRMED, SalesOrderStatus.FULFILLING}:
        return {"status": "SKIPPED", "reason": "生产任务已完成；关联销售订单当前状态不允许正常完结。", **statuses}
    if not sales_etag or sales_etag != etag_for_instance(order):
        return {"status": "SKIPPED", "reason": "生产任务已完成；销售订单版本缺失或已变化，未同步销售状态，请刷新销售订单后处理。", **statuses}
    progress = sales_order_completion_progress(order)
    if progress["blockers"]:
        return {"status": "SKIPPED", "reason": "生产任务已完成；销售订单未满足完结条件：" + "；".join(progress["blockers"]) + "。", **statuses}
    completed = complete_sales_order(
        order=order, exception_close=False, reason=reason,
        actor_employee=request.employee, request=_version_request(request, sales_etag),
    )
    if visible:
        statuses["after_status"] = completed.status
    return {"status": "COMPLETED", "reason": "生产任务及关联销售订单均已完成。", **statuses}


@transaction.atomic
def complete_schedule(*, schedule_id, validated_data, request):
    current = _authorized_schedule(request, schedule_id)

    # 排产编辑、报工和成品入库也先锁排产/任务，锁后重新计算，避免提交旧进度。
    schedule = ProductionSchedule.objects.select_for_update().get(pk=current.pk)
    require_matching_etag(request, schedule)
    task = ProductionTask.objects.select_for_update().get(pk=schedule.production_task_id)
    require_matching_etag(_version_request(request, validated_data["task_etag"]), task)
    if schedule.record_status != ScheduleStatus.ACTIVE:
        raise Conflict("只有有效排产计划可以完成订单。")
    if task.status != ProductionTaskStatus.IN_PRODUCTION or task.archived_at is not None:
        raise Conflict("只有未归档且生产中的生产任务单可以完成。")
    # 工价审批以任务产品行作并发锁；同锁避免核验后有效工价被同时切换。
    list(ProductionTaskProduct.objects.select_for_update(of=("self",)).filter(
        schedule_products__schedule=schedule, schedule_products__removed_at__isnull=True,
    ).order_by("pk"))
    results = schedule_progress_statuses([schedule.pk])
    progress = results[0]["progress"] if results else {}
    required = {"MATERIAL", "METAL", "SEWING", "ASSEMBLY"}
    if set(progress) != required or any(progress[key].get("percentage") != 100 for key in required):
        raise Conflict({"detail": "四项进度全部达到100%后才能完成订单。", "progress": progress})

    before_task_status = task.status
    task = close_production_task(
        task=task, target_status=ProductionTaskStatus.COMPLETED, reason=validated_data["reason"],
        actor_employee=request.employee, request=request,
    )
    # 按用户确认的百分比门槛完成状态；保留原实际数、合格数及所有生产批次。
    task.completed_at = timezone.now()
    task.save(update_fields=["completed_at", "updated_at"])
    sales_sync = _sync_sales_order(
        task=task, sales_etag=validated_data.get("sales_order_etag"),
        request=request, reason=validated_data["reason"],
    )
    production_sync = {"before_status": before_task_status, "after_status": task.status}
    schedule.updated_by_employee = request.employee
    schedule.save(update_fields=["updated_by_employee", "updated_at"])
    write_audit_log(
        object_type="PRODUCTION_SCHEDULE", object_id=schedule.pk,
        action="COMPLETED", actor_employee=request.employee,
        context_type="PRODUCTION_TASK", context_id=task.pk,
        after_data={"progress": progress, "reason": validated_data["reason"],
                    "production_sync": production_sync, "sales_sync": sales_sync},
        request=request,
    )
    return schedule, {
        "schedule_id": str(schedule.pk), "production_task_id": str(task.pk),
        "production_task_status": task.status, "progress": progress,
        "production_sync": production_sync, "sales_sync": sales_sync,
    }
