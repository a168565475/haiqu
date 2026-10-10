"""装配来源及入库服务；复用既有成品原单和余额，不核对逐项领料。"""
import hashlib
import json
from decimal import Decimal, ROUND_FLOOR

from django.db import connection, transaction
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct
from apps.production_scheduling.selectors import schedule_items_for_category, accessible_production_schedules
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from .models import FinishedGoodsReceipt, AssemblyReceiptSource
from .services import create_finished_goods_receipt
from .assembly_reporting_limits import assembly_reporting_limit


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


class ReceiptRequestConflict(Conflict):
    api_error_code = 'RECEIPT_REQUEST_CONFLICT'


def load_context(request, plan_id, *, lock=False):
    plan = get_object_or_404(schedule_items_for_category(request, 'ASSEMBLY'), pk=plan_id)
    if lock:
        # 与排产编辑/作废保持计划→订单→产品的顺序。
        ProductionSchedule.objects.select_for_update().get(pk=plan.schedule_id)
        ProductionTask.objects.select_for_update().get(pk=plan.schedule.production_task_id)
        ProductionTaskProduct.objects.select_for_update().get(pk=plan.product_line_id)
        ProductionScheduleProduct.objects.select_for_update().get(pk=plan.pk)
        plan = get_object_or_404(schedule_items_for_category(request, 'ASSEMBLY'), pk=plan_id)
    task, product = plan.schedule.production_task, plan.product_line
    if task.status != 'IN_PRODUCTION':
        raise Conflict('只有生产中的订单产品可以办理成品入库。')
    if not plan.crafts.filter(removed_at__isnull=True, plan_category='ASSEMBLY',
            craft_type_snapshot='INTERNAL', craft__status='ACTIVE').exists():
        raise Conflict('装配工序已停用，请先核对计划。')
    total = FinishedGoodsReceipt.objects.filter(production_task_product=product).aggregate(total=Sum('received_quantity'))['total'] or 0
    maximum = int((Decimal(product.quantity)*(1+Decimal(task.order_tolerance_percent)/100)).to_integral_value(rounding=ROUND_FLOOR))
    if product.quantity <= 0 or not product.unit_id or maximum < 0:
        raise ValidationError('订单数量、单位或允许偏差不完整。')
    order_maximum = maximum
    reporting = assembly_reporting_limit(product)
    maximum = min(maximum, reporting['reported_minimum'])
    values = dict(schedule_product_id=str(plan.pk), schedule_number=plan.schedule.schedule_number,
        production_task_product_id=str(product.pk), task_number=task.task_number, order_number=task.order_number,
        product_number=product.product_number_snapshot, product_name=product.product_name_snapshot,
        item_number=product.item_number_snapshot, specification=product.specification_snapshot,
        actual_color=product.color_name_snapshot, unit_id=str(product.unit_id), unit_name=product.unit.unit_name,
        order_quantity=int(product.quantity), tolerance_percent=str(task.order_tolerance_percent),
        maximum_receivable=maximum, received_total=int(total), remaining_receivable=max(0,maximum-int(total)),
        order_maximum=order_maximum, **reporting,
        receipt_date=str(timezone.localdate()), actor_name=request.employee.display_name)
    revision = digest([values, str(plan.updated_at), str(plan.schedule.updated_at), str(task.updated_at), str(product.updated_at)])
    return plan, product, values, '"'+revision+'"'


@transaction.atomic
def confirm_assembly_receipt(request, data):
    payload_hash = digest(data)
    lock_id = int.from_bytes(hashlib.sha256(str(data['request_id']).encode()).digest()[:8], 'big', signed=True)
    with connection.cursor() as cursor:
        cursor.execute('SELECT pg_advisory_xact_lock(%s)', [lock_id])
    # 已成功原单按来源数据权限核对，不受后来作废计划或移除工序影响。
    previous = AssemblyReceiptSource.objects.select_related('receipt','schedule_product').filter(request_id=data['request_id']).first()
    if previous:
        get_object_or_404(accessible_production_schedules(request),pk=previous.schedule_product.schedule_id)
        if previous.payload_hash != payload_hash:
            raise ReceiptRequestConflict('同一入库请求不能修改内容，请先核对原单。')
        return previous.receipt, True
    plan, product, context, etag = load_context(request, data['schedule_product_id'], lock=True)
    if not request.headers.get('If-Match'):
        raise PreconditionRequired('请先读取当前入库额度。')
    if request.headers.get('If-Match') != etag:
        raise PreconditionFailed('订单或入库额度已变化，请刷新后重新确认。')
    validated = dict(production_task_product_id=product.pk, location_id=data['location_id'],
        supplier=None, expected_received_total=context['received_total'], received_quantity=data['received_quantity'],
        quantity_per_box=data.get('quantity_per_box'), unit_id=product.unit_id,
        actual_color=data['actual_color'], remark=data.get('remark',''))
    receipt = create_finished_goods_receipt(validated_data=validated, actor_employee=request.employee, request=request)
    AssemblyReceiptSource.objects.create(receipt=receipt, schedule_product=plan, request_id=data['request_id'],
        payload_hash=payload_hash, receipt_date=data['receipt_date'], snapshot={**context,
            'received_after':context['received_total']+receipt.received_quantity})
    return receipt, False


def assembly_progress_for_plans(plans):
    """仅供入库统计；不得用于更新或覆盖报工计划状态。"""
    totals = dict(FinishedGoodsReceipt.objects.filter(production_task_product_id__in=[p.product_line_id for p in plans])
        .values('production_task_product_id').annotate(total=Sum('received_quantity')).values_list('production_task_product_id','total'))
    return {str(p.pk): {'complete':totals.get(p.product_line_id,0)>=p.product_line.quantity,
        'received':int(totals.get(p.product_line_id,0)), 'required':int(p.product_line.quantity)} for p in plans}
