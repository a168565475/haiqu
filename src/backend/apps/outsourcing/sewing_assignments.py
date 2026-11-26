"""按生产产品读取车缝总单冻结的本厂部位，兼容没有分工快照的历史业务。"""
from django.db.models import Exists, OuterRef, Q, Subquery
from rest_framework.exceptions import ValidationError

from apps.inventory.models import InternalSemiFinishedReceiptLine
from apps.material_issues.models import MaterialIssueAuditEvent
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_reporting.models import WageSchemeLine, WorkReport, WorkReportLine
from .models import OutsourcingFactory, TubeOutsourcingOrder


def internal_sewing_factory_id():
    # 业务档案只在新建时解析；后续筛选、发货和计价都读总单已保存的分工。
    matches = list(OutsourcingFactory.objects.filter(Q(factory_number='JG-3EE7AD633E92') | Q(name='本厂'),
                                                     status='ACTIVE').values_list('pk', flat=True)[:2])
    if len(matches) > 1:
        raise ValidationError({'factory_id': '本厂加工厂编号和名称对应的启用档案不唯一，请先核对。'})
    return matches[0] if matches else None


def internal_sewing_assignment_in_use(order):
    assignment = order.source_snapshot.get('sewing_part_assignments')
    if not assignment or not assignment['internal']:
        return False
    parts = [row['component_identity'] for row in assignment['internal']]
    if WorkReportLine.objects.filter(report__product_line_id=order.product_line_id,
            work_item__bom_component_identity__in=parts, created_at__gte=order.created_at).exists():
        return True
    if InternalSemiFinishedReceiptLine.objects.filter(receipt__schedule_product__product_line_id=order.product_line_id,
            receipt__plan_category='SEWING', component_identity__in=parts, created_at__gte=order.created_at).exists():
        return True
    if MaterialIssueAuditEvent.objects.filter(issue__product_line_id=order.product_line_id, action='CREATED',
            issue__status__in=['PENDING_REVIEW', 'ISSUED'], snapshot__plan_source__plan_category='SEWING',
            created_at__gte=order.created_at).exists():
        return True
    return WageSchemeLine.objects.filter(scheme__product_line_id=order.product_line_id,
        scheme__scope_craft__plan_category='SEWING', bom_component_identity_snapshot__in=parts,
        scheme__status__in=['PENDING_APPROVAL', 'APPROVED', 'SUPERSEDED'],
        scheme__events__action__in=['SUBMITTED', 'APPROVED'], scheme__events__created_at__gte=order.created_at).exists()


def _sewing_scope_rows():
    sewing_plans = TubeOutsourcingOrder.objects.filter(
        product_line_id=OuterRef('product_line_id'), is_plan=True, craft__outsourcing_code='SEWING',
    )
    plans = sewing_plans.exclude(status='CANCELLED')
    assignments = plans.filter(source_snapshot__has_key='sewing_part_assignments')
    external_crafts = ProductionScheduleProductCraft.objects.filter(
        schedule_product__product_line_id=OuterRef('product_line_id'), removed_at__isnull=True,
        schedule_product__removed_at__isnull=True, schedule_product__schedule__record_status='ACTIVE',
        craft_type_snapshot='EXTERNAL', craft__outsourcing_code='SEWING',
    )
    reports = WorkReport.objects.filter(product_line_id=OuterRef('product_line_id'),
                                        scheme__scope_craft__plan_category='SEWING')
    issues = MaterialIssueAuditEvent.objects.filter(
        issue__product_line_id=OuterRef('product_line_id'), action='CREATED',
        issue__status__in=['ISSUED', 'PENDING_REVIEW'], snapshot__plan_source__plan_category='SEWING',
    )
    return ProductionScheduleProduct.objects.annotate(
        sewing_assignment=Subquery(assignments.order_by('-created_at', '-pk')
                                   .values('source_snapshot__sewing_part_assignments')[:1]),
        needs_sewing_assignment=(Exists(external_crafts) & ~Exists(plans) &
            (Exists(sewing_plans.filter(source_snapshot__has_key='sewing_part_assignments')) |
             (~Exists(reports) & ~Exists(issues)))),
    )


def internal_sewing_products():
    """保留按原规则办理的计划和新总单中确有本厂部位的计划。"""
    return _sewing_scope_rows().filter(needs_sewing_assignment=False).filter(
        Q(sewing_assignment__isnull=True) | Q(sewing_assignment__internal__0__isnull=False))


def _scope(assignment, pending):
    if assignment is not None:
        return {row['component_identity']: row['quantity'] for row in assignment['internal']}
    return {} if pending else None


def sewing_part_scopes(schedule_product_ids):
    rows = _sewing_scope_rows().filter(pk__in=schedule_product_ids)
    return {pk: _scope(assignment, pending) for pk, assignment, pending in
            rows.values_list('pk', 'sewing_assignment', 'needs_sewing_assignment')}


def sewing_part_scope(schedule_product_id=None, *, product_line_id=None):
    rows = _sewing_scope_rows()
    if product_line_id is not None:
        rows = rows.filter(product_line_id=product_line_id, removed_at__isnull=True, schedule__record_status='ACTIVE')
    else:
        rows = rows.filter(pk=schedule_product_id)
    values = rows.order_by('pk').values_list('sewing_assignment', 'needs_sewing_assignment').first()
    return _scope(*values) if values else None
