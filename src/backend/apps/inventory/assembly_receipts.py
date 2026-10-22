"""装配来源及入库服务；复用既有成品原单和余额，不核对逐项领料。"""
import hashlib
import json
from decimal import Decimal, ROUND_FLOOR

from django.db import connection, transaction
from django.db.models.deletion import ProtectedError
from django.db.models import Sum
from django.shortcuts import get_object_or_404
from django.utils import timezone
from rest_framework.exceptions import PermissionDenied, ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.api.concurrency import PreconditionFailed, PreconditionRequired, require_matching_etag
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct
from apps.production_scheduling.selectors import accessible_production_schedules
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from .models import FinishedGoodsReceipt, FinishedGoodsReceiptStatus, AssemblyReceiptSource
from .services import create_finished_goods_receipt, confirm_finished_goods_receipt
from .assembly_reporting_limits import assembly_reporting_limit
from .receipt_permissions import can_delete_pending_receipt, receipt_plans_for_category


def digest(value):
    return hashlib.sha256(json.dumps(value, sort_keys=True, default=str, ensure_ascii=False).encode()).hexdigest()


class ReceiptRequestConflict(Conflict):
    api_error_code = 'RECEIPT_REQUEST_CONFLICT'


def load_context(request, plan_id, *, lock=False, exclude_receipt_id=None, confirmation=False):
    plan = get_object_or_404(receipt_plans_for_category(request, 'ASSEMBLY', confirmation=confirmation), pk=plan_id)
    if lock:
        # 与排产编辑/作废保持计划→订单→产品的顺序。
        ProductionSchedule.objects.select_for_update().get(pk=plan.schedule_id)
        ProductionTask.objects.select_for_update().get(pk=plan.schedule.production_task_id)
        ProductionTaskProduct.objects.select_for_update().get(pk=plan.product_line_id)
        ProductionScheduleProduct.objects.select_for_update().get(pk=plan.pk)
        plan = get_object_or_404(receipt_plans_for_category(request, 'ASSEMBLY', confirmation=confirmation), pk=plan_id)
    task, product = plan.schedule.production_task, plan.product_line
    if task.status != 'IN_PRODUCTION':
        raise Conflict('只有生产中的订单产品可以办理成品入库。')
    if not plan.crafts.filter(removed_at__isnull=True, plan_category='ASSEMBLY',
            craft_type_snapshot='INTERNAL', craft__status='ACTIVE').exists():
        raise Conflict('装配工序已停用，请先核对计划。')
    receipt_rows = FinishedGoodsReceipt.objects.filter(production_task_product=product)
    if exclude_receipt_id is not None:
        receipt_rows = receipt_rows.exclude(pk=exclude_receipt_id)
    total = receipt_rows.aggregate(total=Sum('received_quantity'))['total'] or 0
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
    receipt = create_finished_goods_receipt(
        validated_data=validated, actor_employee=request.employee, request=request,
    )
    AssemblyReceiptSource.objects.create(receipt=receipt, schedule_product=plan, request_id=data['request_id'],
        payload_hash=payload_hash, receipt_date=data['receipt_date'], snapshot={**context,
            'received_after':context['received_total']+receipt.received_quantity,
            'status': receipt.status})
    from .notification_events import assembly_receipt_submitted
    assembly_receipt_submitted(receipt, request.employee)
    return receipt, False


@transaction.atomic
def confirm_pending_assembly_receipt(request, receipt_id):
    source = lock_assembly_receipt_source(receipt_id)
    if source.receipt.status == FinishedGoodsReceiptStatus.PENDING:
        _plan, _product, context, _etag = load_context(
            request, source.schedule_product_id, lock=True, exclude_receipt_id=source.receipt_id, confirmation=True,
        )
        if source.receipt.received_quantity > context['remaining_receivable']:
            raise ValidationError({'receipt': '提交后订单额度或报工最低数量已变化，当前入库数量不能确认。'})
    receipt, replayed = confirm_finished_goods_receipt(
        receipt_id=source.receipt_id, actor_employee=request.employee, request=request,
    )
    if not replayed:
        source.snapshot = {**source.snapshot, 'status': receipt.status,
                           'confirmed_at': receipt.confirmed_at.isoformat() if receipt.confirmed_at else None,
                           'confirmed_by_employee_id': str(receipt.confirmed_by_employee_id)}
        source.save(update_fields=['snapshot'])
        # 通知版本包含来源快照，必须在确认信息保存后登记，避免消息立即失效。
        from .notification_events import assembly_receipt_confirmed
        assembly_receipt_confirmed(receipt, request.employee)
    return receipt, replayed


def lock_assembly_receipt_source(receipt_id):
    source = get_object_or_404(AssemblyReceiptSource.objects.select_related(
        'schedule_product__schedule'), receipt_id=receipt_id)
    plan = source.schedule_product
    # 与装配提交、确认一致：计划→任务→产品→计划产品→来源→原单。
    ProductionSchedule.objects.select_for_update().get(pk=plan.schedule_id)
    ProductionTask.objects.select_for_update().get(pk=plan.schedule.production_task_id)
    ProductionTaskProduct.objects.select_for_update().get(pk=plan.product_line_id)
    ProductionScheduleProduct.objects.select_for_update().get(pk=plan.pk)
    return get_object_or_404(AssemblyReceiptSource.objects.select_for_update(of=('self',)).select_related(
        'receipt', 'schedule_product'), receipt_id=receipt_id)


@transaction.atomic
def delete_pending_assembly_receipt(request, receipt_id):
    from apps.access_control.module_policy import has_permission
    from apps.core.auth import active_employee_for
    if active_employee_for(request.user) is None or not has_permission(request, 'inventory.delete_finishedgoodsreceipt'):
        raise PermissionDenied('没有删除装配待入库记录的权限。')
    source = lock_assembly_receipt_source(receipt_id)
    receipt = get_object_or_404(FinishedGoodsReceipt.objects.select_for_update(), pk=receipt_id)
    if receipt.status != FinishedGoodsReceiptStatus.PENDING:
        raise Conflict('已入库记录不能删除。')
    if not can_delete_pending_receipt(request, receipt, 'ASSEMBLY'):
        raise PermissionDenied('只能删除本人提交的待入库记录。')
    require_matching_etag(request, receipt)
    if (receipt.source_type != 'PRODUCTION_ORDER' or receipt.source_sample_inventory_line_id
            or receipt.confirmed_at is not None or receipt.remaining_quantity != 0
            or receipt.remaining_box_slots not in (None, 0) or receipt.outbound_lines.exists()):
        raise Conflict('入库记录已有库存或出库引用，不能删除。')
    try:
        from apps.core.audit import write_audit_log
        write_audit_log(object_type='FINISHED_GOODS_RECEIPT', object_id=receipt.pk, action='DELETED',
            actor_employee=request.employee, context_type='PRODUCTION_SCHEDULE',
            context_id=source.schedule_product.schedule_id, request=request,
            before_data={'receipt_number': receipt.receipt_number,
                         'product_line_id': str(receipt.production_task_product_id), 'status': receipt.status})
        source.delete()
        receipt.delete()
    except ProtectedError as error:
        raise Conflict('入库记录已有业务引用，不能删除。') from error


def assembly_progress_for_plans(plans):
    """仅供入库统计；不得用于更新或覆盖报工计划状态。"""
    totals = dict(FinishedGoodsReceipt.objects.filter(
        production_task_product_id__in=[p.product_line_id for p in plans],
        status=FinishedGoodsReceiptStatus.CONFIRMED,
    )
        .values('production_task_product_id').annotate(total=Sum('received_quantity')).values_list('production_task_product_id','total'))
    return {str(p.pk): {'complete':totals.get(p.product_line_id,0)>=p.product_line.quantity,
        'received':int(totals.get(p.product_line_id,0)), 'required':int(p.product_line.quantity)} for p in plans}
