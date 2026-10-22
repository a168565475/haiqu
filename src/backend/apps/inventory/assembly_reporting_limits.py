"""装配报工只提供可收货额度；实际库存仍由仓库入库单产生。"""
from decimal import Decimal, ROUND_FLOOR

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_reporting.models import WageScheme, WorkReportLine
from .models import FinishedGoodsReceipt, FinishedGoodsReceiptStatus


def assembly_reporting_limits(product_lines):
    # 额度按订单产品共用，包含其有效装配计划的全部应做工序。
    product_ids = [line.pk for line in product_lines]
    scopes = {key: set() for key in product_ids}
    for product_id, craft_id in ProductionScheduleProductCraft.objects.filter(
        schedule_product__product_line_id__in=product_ids,
        schedule_product__removed_at__isnull=True,
        schedule_product__schedule__record_status='ACTIVE', removed_at__isnull=True,
        craft_type_snapshot='INTERNAL', plan_category='ASSEMBLY',
    ).values_list('schedule_product__product_line_id', 'craft_id'):
        scopes[product_id].add(craft_id)
    craft_ids = set().union(*scopes.values()) if scopes else set()
    today = timezone.localdate()
    schemes = WageScheme.objects.filter(
        product_line_id__in=product_ids, scope_craft_id__in=craft_ids,
        status='APPROVED', effective_from__lte=today,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=today)).prefetch_related('lines__work_item')
    by_craft = {}
    for scheme in schemes:
        by_craft.setdefault((scheme.product_line_id, scheme.scope_craft_id), []).append(scheme)
    totals = dict(WorkReportLine.objects.filter(
        report__product_line_id__in=product_ids, work_item__craft_id__in=craft_ids,
    ).values('work_item_id').annotate(total=Sum('quantity')).values_list('work_item_id', 'total'))
    result = {}
    for product_id, crafts in scopes.items():
        missing = not crafts
        required = {}
        for craft_id in crafts:
            matches = by_craft.get((product_id, craft_id), [])
            if len(matches) != 1:
                missing = True
                continue
            lines = [line for line in matches[0].lines.all() if line.status == 'ACTIVE']
            if not lines:
                missing = True
            for line in lines:
                if line.counting_mode != 'ORDER' or not line.required_quantity_snapshot or line.required_quantity_snapshot <= 0:
                    missing = True
                required[line.work_item_id] = line
        operations = [dict(work_item_id=str(key), operation=line.operation_name_snapshot,
            reported_quantity=str(totals.get(key, Decimal('0')))) for key, line in sorted(required.items(), key=lambda row: str(row[0]))]
        minimum = min((totals.get(key, Decimal('0')) for key in required), default=Decimal('0'))
        if missing:
            minimum = Decimal('0')
        result[product_id] = {'reported_minimum': max(0, int(minimum.to_integral_value(rounding=ROUND_FLOOR))),
            'reporting_basis_ready': not missing, 'reporting_operations': operations}
    return result


def assembly_reporting_limit(product_line):
    return assembly_reporting_limits([product_line])[product_line.pk]


def is_assembly_report(report):
    # 按排产时的工艺快照判断，后续改工艺分类或车间名称不能绕过保护。
    return ProductionScheduleProductCraft.objects.filter(
        schedule_product_id=report.schedule_product_id,
        craft_id=report.scheme.scope_craft_id, plan_category='ASSEMBLY',
        craft_type_snapshot='INTERNAL',
    ).exists()


def assert_reports_cover_receipts(product_line):
    """调用者已持有订单产品锁；编辑/删除失败时整个报工事务回滚。"""
    received = FinishedGoodsReceipt.objects.filter(
        production_task_product_id=product_line.pk,
        status=FinishedGoodsReceiptStatus.CONFIRMED,
    ).aggregate(
        total=Sum('received_quantity'))['total'] or 0
    if not received:
        return
    limit = assembly_reporting_limit(product_line)
    if limit['reported_minimum'] < received:
        raise ValidationError({'lines': f"已累计入库 {received}，修改后的装配工序最低报工量为 {limit['reported_minimum']}，不能低于已入库数量；原记录未修改。"})
