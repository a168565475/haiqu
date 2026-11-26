"""厂内裁片/部位首次产出占用；外发回货不使用这里的上限。"""
from collections import defaultdict
from decimal import Decimal

from django.db.models import Sum


def component_required_quantity(line, order_quantity):
    from apps.boms.component_parts import required_component_quantity
    return Decimal(required_component_quantity(line, order_quantity))


def direct_output_usage(product_id, component_kind, *, exclude_order_id=None, exclude_issue_id=None):
    from apps.outsourcing.models import TubeOutsourcingInput, TubeOutsourcingLine
    source_kind = {'CUT_PIECE': 'CUTTING', 'SEWN_PART': 'SEWING'}[component_kind]
    if component_kind == 'CUT_PIECE':
        rows = TubeOutsourcingInput.objects.filter(order__product_line_id=product_id,
            source_kind=source_kind, order__is_plan=False, bom_line__component_kind=component_kind)
    else:
        rows = TubeOutsourcingLine.objects.filter(order__product_line_id=product_id,
            order__source_kind=source_kind, order__is_plan=False, bom_line__component_kind=component_kind)
    if exclude_order_id:
        rows = rows.exclude(order_id=exclude_order_id)
    usage = defaultdict(lambda: {'reserved': Decimal(0), 'dispatched': Decimal(0)})
    for statuses, field in [(['PENDING_DISPATCH'], 'reserved'), (['PROCESSING', 'COMPLETED'], 'dispatched')]:
        for row in rows.filter(order__status__in=statuses).values('component_identity').annotate(total=Sum('quantity')):
            usage[str(row['component_identity'])][field] = row['total']
    if component_kind == 'CUT_PIECE':
        printed = TubeOutsourcingLine.objects.filter(order__product_line_id=product_id,
            order__source_kind='CUTTING', order__is_plan=False, order__source_snapshot__screen_print_pieces=True,
            order__status__in=['PROCESSING', 'COMPLETED'])
        if exclude_order_id:
            printed = printed.exclude(order_id=exclude_order_id)
        for row in printed.values('component_identity').annotate(total=Sum('quantity')):
            usage[str(row['component_identity'])]['dispatched'] += row['total']
        from apps.material_issues.models import MaterialIssueLine
        issues = MaterialIssueLine.objects.filter(issue__product_line_id=product_id,
            conversion_snapshot__source_kind='CUTTING_DIRECT', semi_requirement__bom_line__component_kind='CUT_PIECE')
        if exclude_issue_id:
            issues = issues.exclude(issue_id=exclude_issue_id)
        for status, field, quantity in [('PENDING_REVIEW', 'reserved', 'requested_quantity'),
                                        ('ISSUED', 'dispatched', 'issued_quantity')]:
            for row in issues.filter(issue__status=status).values('semi_requirement__component_identity').annotate(total=Sum(quantity)):
                usage[str(row['semi_requirement__component_identity'])][field] += row['total'] or Decimal(0)
    return usage


def first_output_available(product_id, line, order_quantity, *, exclude_order_id=None, exclude_receipt_id=None, exclude_issue_id=None):
    from .models import InternalSemiFinishedReceiptLine
    rows = InternalSemiFinishedReceiptLine.objects.filter(receipt__schedule_product__product_line_id=product_id,
        component_identity=line.component_identity, bom_line__component_kind=line.component_kind)
    if exclude_receipt_id:
        rows = rows.exclude(receipt_id=exclude_receipt_id)
    received = rows.aggregate(total=Sum('quantity'))['total'] or Decimal(0)
    direct = direct_output_usage(product_id, line.component_kind,
        exclude_order_id=exclude_order_id, exclude_issue_id=exclude_issue_id).get(str(line.component_identity), {})
    return max(component_required_quantity(line, order_quantity) - received
               - direct.get('dispatched', 0) - direct.get('reserved', 0), Decimal(0))
