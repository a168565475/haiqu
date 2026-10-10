"""管材工价变化后的计划复核；库存额度与逐计划进度分别核算。"""
from decimal import Decimal

from django.db.models import Q, Sum
from django.utils import timezone

from apps.production_scheduling.models import ProductionScheduleProductCraft, ScheduleStatus
from apps.workshop_config.constants import METAL_WORKSHOP_NAME
from apps.workshop_config.models import Craft, CraftType, PlanCategory

from .models import (
    WageScheme, WageSchemeLineStatus, WageSchemeStatus, WorkReportLine,
    WorkshopPlanExecution, WorkshopPlanStatus,
)


def is_tube_craft_scope(product_line_id, craft_id):
    """原排产快照优先，工艺改名或修改分类不能绕过已发生的管材保护。"""
    if not product_line_id or not craft_id:
        return False
    if ProductionScheduleProductCraft.objects.filter(
        schedule_product__product_line_id=product_line_id,
        craft_id=craft_id, craft_type_snapshot=CraftType.INTERNAL,
        plan_category=PlanCategory.METAL,
    ).exists():
        return True
    return Craft.objects.filter(pk=craft_id, craft_type=CraftType.INTERNAL).filter(
        Q(plan_category=PlanCategory.METAL) | Q(workshop__name=METAL_WORKSHOP_NAME)
    ).exists()


def is_tube_scheme(scheme):
    return bool(scheme) and is_tube_craft_scope(scheme.product_line_id, scheme.scope_craft_id)


def is_current_tube_scheme(scheme, *, as_of=None):
    if not is_tube_scheme(scheme) or scheme.status != WageSchemeStatus.APPROVED:
        return False
    as_of = as_of or timezone.localdate()
    if not scheme.effective_from or scheme.effective_from > as_of:
        return False
    if scheme.effective_to and scheme.effective_to < as_of:
        return False
    applicable = WageScheme.objects.filter(
        product_line_id=scheme.product_line_id, workshop_id=scheme.workshop_id,
        scope_craft_id=scheme.scope_craft_id, status=WageSchemeStatus.APPROVED,
        effective_from__lte=as_of,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of))
    return applicable.count() == 1 and applicable.filter(pk=scheme.pk).exists()


def tube_plan_is_complete(schedule_product_id, scheme, *, cumulative_by_work_item=None):
    """使用原逐计划规则，不把其他计划的报工量用于当前计划完成。"""
    required = [line for line in scheme.lines.all() if line.status == WageSchemeLineStatus.ACTIVE]
    if not required or any(
        line.required_quantity_snapshot is None or line.required_quantity_snapshot <= 0
        for line in required
    ):
        return False
    if cumulative_by_work_item is None:
        cumulative_by_work_item = {
            row['work_item_id']: row['quantity'] for row in WorkReportLine.objects.filter(
                report__schedule_product_id=schedule_product_id,
                report__workshop_id=scheme.workshop_id,
                work_item_id__in=[line.work_item_id for line in required],
            ).values('work_item_id').annotate(quantity=Sum('quantity'))
        }
    return all(
        cumulative_by_work_item.get(line.work_item_id, Decimal('0')) >= line.required_quantity_snapshot
        for line in required
    )


def reopen_tube_plans_for_scheme(scheme, actor=None):
    """调用者已取得统一管材锁；只重开，不自动完成或修改历史报工。"""
    if not is_current_tube_scheme(scheme):
        return []
    executions = WorkshopPlanExecution.objects.select_for_update(of=('self',)).filter(
        schedule_product__product_line_id=scheme.product_line_id,
        schedule_product__removed_at__isnull=True,
        schedule_product__schedule__record_status=ScheduleStatus.ACTIVE,
        craft_id=scheme.scope_craft_id, status=WorkshopPlanStatus.COMPLETED,
    )
    changes = []
    for execution in executions.order_by('pk'):
        if not ProductionScheduleProductCraft.objects.filter(
            schedule_product_id=execution.schedule_product_id, craft_id=scheme.scope_craft_id,
            removed_at__isnull=True, craft_type_snapshot=CraftType.INTERNAL,
            plan_category=PlanCategory.METAL,
        ).exists():
            continue
        if tube_plan_is_complete(execution.schedule_product_id, scheme):
            continue
        changes.append(str(execution.pk))
        execution.status = WorkshopPlanStatus.IN_PROGRESS
        execution.completed_at = None
        execution.completed_by_employee = None
        execution.save(update_fields=['status', 'completed_at', 'completed_by_employee', 'updated_at'])
    return changes
