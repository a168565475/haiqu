"""管材报工额度的只读归集及事务保护；不创建库存、不改历史工资。"""
from collections import defaultdict
from dataclasses import asdict
from datetime import date, timedelta
from decimal import Decimal

from django.db import connection
from django.db.models import Count, Exists, F, OuterRef, Prefetch, Q, Sum
from django.db.models.functions import Floor
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionFailed
from apps.material_issues.models import (MaterialIssue, MaterialIssueLine, MaterialIssueAuditEvent,
                                        MaterialIssuePublicStockAllocation, MetalProcessingSource,
                                        OriginalHandoffPublicTransition)
from apps.material_issues.processing_selectors import digest, frozen_source
from apps.products.material_identity import resolve_bom_line_raw_material
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.workshop_reporting.models import WageScheme, WageSchemeLine, WorkReportLine
from .models import InternalSemiFinishedReceiptLine
from .tube_processing_quantities import TubeQuantityError, calculate_tube_allowance, whole_pieces


def _is_implicit_piece_unit(unit_name):
    """金工报工页面不展示单位，空快照按“支”处理；显式其他单位仍拒绝。"""
    normalized = (unit_name or "").strip()
    return not normalized or normalized == "支"


def lock_tube_product_scope(product_line_id):
    """在任何业务行锁前调用。按旧交接的领料优先顺序锁定同产品全部来源。

    同一产品跨排产共享额度，不能仅锁当前计划。锁可在同事务重入；行锁后
    重查来源集合，防止等待期间新增领料漏出范围。S3写入也必须使用此入口。
    """
    if not connection.in_atomic_block:
        raise RuntimeError('管材额度写入必须在事务中执行。')
    product = ProductionTaskProduct.objects.only('production_task_id').get(pk=product_line_id)
    issue_ids = list(MaterialIssue.objects.filter(product_line_id=product_line_id)
                     .order_by('pk').select_for_update(of=('self',)).values_list('pk', flat=True))
    list(MetalProcessingSource.objects.filter(issue_line__issue_id__in=issue_ids)
         .order_by('pk').select_for_update(of=('self',)).values_list('pk', flat=True))
    plans = ProductionScheduleProduct.objects.filter(product_line_id=product_line_id)
    schedule_ids = list(plans.order_by('schedule_id').values_list('schedule_id', flat=True).distinct())
    list(ProductionSchedule.objects.filter(pk__in=schedule_ids).order_by('pk')
         .select_for_update(of=('self',)).values_list('pk', flat=True))
    ProductionTask.objects.select_for_update(of=('self',)).get(pk=product.production_task_id)
    product = ProductionTaskProduct.objects.select_for_update(of=('self',)).get(pk=product_line_id)
    list(plans.order_by('pk').select_for_update(of=('self',)).values_list('pk', flat=True))
    if issue_ids != list(MaterialIssue.objects.filter(product_line_id=product_line_id)
                         .order_by('pk').values_list('pk', flat=True)):
        raise PreconditionFailed('领料来源已变化，请刷新后重试。')
    if schedule_ids != list(plans.order_by('schedule_id').values_list('schedule_id', flat=True).distinct()):
        raise PreconditionFailed('排产范围已变化，请刷新后重试。')
    return product


def _metal_schemes(product_line_id):
    from apps.production_scheduling.models import ProductionScheduleProductCraft
    craft_ids = ProductionScheduleProductCraft.objects.filter(
        schedule_product__product_line_id=product_line_id, craft_type_snapshot='INTERNAL',
        plan_category='METAL').values('craft_id')
    return WageScheme.objects.filter(product_line_id=product_line_id).filter(
        Q(scope_craft_id__in=craft_ids) | Q(scope_craft__plan_category='METAL')
        | Q(scope_craft__workshop__name='金工车间')).filter(scope_craft__craft_type='INTERNAL')


def _usage(product_line_id, *, exclude_tube_order_id=None):
    """累计真实首次产出，不读取公共库存余额，不读取采购批次。"""
    usage = defaultdict(lambda: dict(received=0, dispatched=0, reserved=0, legacy_dispatched=0))
    from apps.outsourcing.models import TubeOutsourcingLine
    tube_rows = TubeOutsourcingLine.objects.filter(
        order__product_line_id=product_line_id, order__source_kind='METAL',
    )
    if exclude_tube_order_id:
        tube_rows = tube_rows.exclude(order_id=exclude_tube_order_id)
    for row in tube_rows.filter(order__status='PENDING_DISPATCH').values('component_identity').annotate(quantity=Sum('quantity')):
        usage[str(row['component_identity'])]['reserved'] += row['quantity']
    for row in tube_rows.filter(order__status__in=['PROCESSING', 'COMPLETED']).values('component_identity').annotate(quantity=Sum('quantity')):
        usage[str(row['component_identity'])]['dispatched'] += row['quantity']
    for row in InternalSemiFinishedReceiptLine.objects.filter(
        receipt__schedule_product__product_line_id=product_line_id, receipt__plan_category='METAL',
    ).values('component_identity').annotate(quantity=Sum('quantity')):
        usage[str(row['component_identity'])]['received'] = row['quantity']
    for row in MetalProcessingSource.objects.filter(
        issue_line__issue__product_line_id=product_line_id,
    ).values('issue_line__requirement__component_identity').annotate(
        dispatched=Sum('dispatched_pieces'), reserved=Sum('reserved_pieces'),
    ):
        key = str(row['issue_line__requirement__component_identity'])
        usage[key]['dispatched'] += row['dispatched']
        usage[key]['reserved'] += row['reserved']
    # 仅明确已有接续凭证的历史实交免于要求新报工；仍占需求及投入，不恢复额度。
    for row in OriginalHandoffPublicTransition.objects.filter(
        original_handoff__source__issue_line__issue__product_line_id=product_line_id,
    ).values('original_handoff__source__issue_line__requirement__component_identity').annotate(
        quantity=Sum('original_handoff__handoff_pieces'),
    ):
        key = str(row['original_handoff__source__issue_line__requirement__component_identity'])
        usage[key]['legacy_dispatched'] = row['quantity']
    return usage


def metal_component_limits(product_line, *, as_of=None, exclude_tube_order_id=None):
    """当前适用方案的稳定工序累计量。返回依据缺失原因，不按名称猜部位。"""
    if not isinstance(product_line, ProductionTaskProduct):
        product_line = ProductionTaskProduct.objects.get(pk=product_line)
    as_of = as_of or timezone.localdate()
    usage = _usage(product_line.pk, exclude_tube_order_id=exclude_tube_order_id)
    bom = Bom.objects.filter(product_line=product_line, archived_at__isnull=True).order_by('-version_number', '-pk').first()
    bom_ready = bom is not None and bom.status == 'VERIFIED' and bom.order_quantity == product_line.quantity
    bom_lines = list(BomLine.objects.filter(section__bom=bom, section__section_type='PROFILE')) if bom else []
    components = defaultdict(list)
    for line in bom_lines:
        components[str(line.component_identity)].append(line)
    approved_schemes = list(_metal_schemes(product_line.pk).filter(status='APPROVED').order_by('pk'))
    schemes = [scheme for scheme in approved_schemes if scheme.effective_from <= as_of
               and (scheme.effective_to is None or scheme.effective_to >= as_of)]
    scheme_lines = list(WageSchemeLine.objects.filter(scheme__in=schemes, status='ACTIVE')
                        .select_related('work_item__unit', 'work_item__operation', 'scheme'))
    operations = defaultdict(list)
    malformed = False
    for line in scheme_lines:
        key = str(line.bom_component_identity_snapshot)
        if key == 'None':
            malformed = True
        operations[key].append(line)
    # 历史行按稳定WorkItem累计，价格或版本变化不影响支数；未来生产日不提前支持今天入库。
    report_rows = WorkReportLine.objects.filter(
        report__product_line=product_line, report__production_date__lte=as_of,
        work_item_id__in=[row.work_item_id for row in scheme_lines],
    ).values('work_item_id', 'unit_name_snapshot', 'scheme_line__counting_mode',
             'scheme_line__bom_component_identity_snapshot').annotate(
                 total_quantity=Sum('quantity'),
                 invalid_quantities=Count('pk', filter=~Q(quantity=Floor(F('quantity')))))
    items = {line.work_item_id: line for line in scheme_lines}
    totals = defaultdict(Decimal)
    invalid_items = set()
    for row in report_rows:
        totals[row['work_item_id']] += row['total_quantity']
        item = items[row['work_item_id']]
        if (row['invalid_quantities'] or not _is_implicit_piece_unit(row['unit_name_snapshot'])
                or row['scheme_line__counting_mode'] != 'PIECE'
                or row['scheme_line__bom_component_identity_snapshot'] != item.bom_component_identity_snapshot):
            invalid_items.add(row['work_item_id'])
    metal_origin = MaterialIssueAuditEvent.objects.filter(
        issue_id=OuterRef('issue_id'), action='CREATED', snapshot__plan_source__plan_category='METAL')
    issued_rows = list(MaterialIssueLine.objects.filter(
        issue__product_line=product_line, issue__status='ISSUED', issue__stock_mode='PUBLIC_V2',
        line_type='RAW', requirement__measurement_kind='PIPE', requirement__product_line=product_line,
    ).annotate(metal_origin=Exists(metal_origin)).filter(metal_origin=True)
        .select_related('requirement', 'unit', 'issue__product_line')
        .prefetch_related(
            Prefetch('issue__audit_events', queryset=MaterialIssueAuditEvent.objects.filter(action='CREATED')),
            Prefetch('public_stock_allocations', queryset=MaterialIssuePublicStockAllocation.objects
                     .select_related('movement', 'balance'))))
    issued = defaultdict(Decimal)
    invalid_inputs = defaultdict(list)
    material_cache = {}
    for row in issued_rows:
        key = str(row.requirement.component_identity)
        lines = components.get(key, [])
        frozen = row.conversion_snapshot
        try:
            if len(lines) != 1 or row.unit.unit_name != '支' or frozen.get('kind') != 'PIPE':
                raise ValueError()
            line = lines[0]
            material, _ = resolve_bom_line_raw_material(line, cache=material_cache)
            if material is None or row.raw_material_id != material.pk or row.requirement.raw_material_id != material.pk:
                raise ValueError()
            frozen_source(row)
            if (str(frozen.get('component_identity')) != key
                    or str(frozen.get('product_line_id')) != str(product_line.pk)
                    or Decimal(str(frozen.get('cutting_length_mm', 0))) != line.cutting_length_mm
                    or Decimal(str(frozen.get('pieces_per_bar', 0))) != line.pieces_per_bar
                    or Decimal(str(frozen.get('raw_bar_length_m', 0))) != line.raw_bar_length_m):
                raise ValueError()
            issued[key] += whole_pieces(row.issued_quantity, '实际领用投入')
        except (ValueError, TypeError, ArithmeticError, ValidationError):
            invalid_inputs[key].append('已领管材原料、单位、部位、切割参数或实际出库凭证与当前BOM不一致。')
    result = {}
    for key in sorted(set(components) | set(usage)):
        lines = components.get(key, [])
        blockers = []
        if not bom_ready or len(lines) != 1:
            blockers.append('请先确认与订单数量一致、部位唯一的最新BOM。')
        part = lines[0].part_name if len(lines) == 1 else key
        component_operations = operations.get(key, [])
        if malformed or not component_operations:
            blockers.append('请先完善工价方案，部位须对应有效工序。')
        operation_totals, evidence = {}, []
        seen_operations = set()
        for line in component_operations:
            item = line.work_item
            identity = (item.craft_id, item.operation_id)
            item_unit_name = item.unit.unit_name if item.unit_id else ''
            if (identity in seen_operations or item.product_line_id != product_line.pk
                    or item.bom_component_identity != line.bom_component_identity_snapshot
                    or item.craft_id != line.scheme.scope_craft_id or item.workshop_id != line.scheme.workshop_id
                    or line.counting_mode != 'PIECE' or item.counting_mode != 'PIECE'
                    or not _is_implicit_piece_unit(line.unit_name_snapshot)
                    or not _is_implicit_piece_unit(item_unit_name)
                    or item.pk in invalid_items):
                blockers.append('工序身份、部位或报工单位不能唯一对应到支，请先修正工价资料。')
            seen_operations.add(identity)
            operation_totals[str(item.pk)] = totals[item.pk]
            evidence.append(dict(work_item_id=str(item.pk), operation_id=str(item.operation_id),
                                 name=line.operation_name_snapshot, scheme_id=str(line.scheme_id),
                                 scheme_number=line.scheme.scheme_number, scheme_version=line.scheme.version,
                                 scheme_revision=line.scheme.revision, quantity=str(totals[item.pk])))
        blockers.extend(invalid_inputs[key])
        values = usage[key]
        allowance = None
        required = None
        try:
            required = whole_pieces(product_line.quantity * lines[0].pieces_per_product, '部位净需求') if len(lines) == 1 else 0
            if not blockers:
                allowance = calculate_tube_allowance(order_required=required, issued=issued[key],
                    operation_totals=operation_totals, **values)
        except (TubeQuantityError, TypeError) as exc:
            blockers.append(str(exc))
        result[key] = dict(component_identity=key, part_name=part, basis_ready=not blockers,
                           blockers=list(dict.fromkeys(blockers)), operations=evidence,
                           required=required, issued=whole_pieces(issued[key], '实际领用投入'),
                           usage={name: str(value) for name, value in values.items()},
                           allowance=asdict(allowance) if allowance else None)
    revision = digest({'product_line_id': str(product_line.pk), 'as_of': str(as_of),
                       'bom_id': str(bom.pk) if bom else None, 'components': result,
                       'approved_versions': [(str(row.pk), row.revision, str(row.effective_from),
                                              str(row.effective_to)) for row in approved_schemes]})
    return dict(product_line_id=str(product_line.pk), as_of=str(as_of), revision=revision, components=result)


def _basis_dates(product_line_id):
    today = timezone.localdate()
    dates = {today}
    for start, end in _metal_schemes(product_line_id).filter(status='APPROVED').values_list('effective_from', 'effective_to'):
        if start and start > today:
            dates.add(start)
        # 有明确截止但无后续版本时也不能静默失去已处理数量的报工依据。
        if end and today <= end < date.max:
            dates.add(end + timedelta(days=1))
    return sorted(dates)


def assert_tube_reports_cover_usage(product_line_id):
    """事务内变更后核验当前及已批准未来版本，失败令改删/审批整体回滚。"""
    usage = _usage(product_line_id)
    protected = {}
    for key, value in usage.items():
        try:
            quantity = whole_pieces(value['received'] + value['dispatched'] + value['reserved']
                                    - value['legacy_dispatched'], '需报工支持的已占用')
        except TubeQuantityError as exc:
            raise ValidationError({'detail': str(exc)}) from exc
        if quantity:
            protected[key] = quantity
    if not protected:
        return
    for as_of in _basis_dates(product_line_id):
        context = metal_component_limits(product_line_id, as_of=as_of)
        for key, used in protected.items():
            row = context['components'].get(key)
            if not row or not row['basis_ready']:
                raise ValidationError({'detail': f'{as_of}的部位报工依据不完整，已有{used}支入库、直接交接或预留，不能保存该变更。'})
            if row['allowance']['reported_minimum'] < used:
                raise ValidationError({'detail': f'“{row["part_name"]}”在{as_of}最低报工仅'
                    f'{row["allowance"]["reported_minimum"]}支，不能低于已处理及预留合计{used}支。'})


def assert_tube_quantity_available(*, product_line_id, requested, expected_revision, exclude_tube_order_id=None):
    """S3入库/直接外发共同入口；调用者须同事务记录首次产出或有效预留。"""
    product = lock_tube_product_scope(product_line_id)
    context = metal_component_limits(product, exclude_tube_order_id=exclude_tube_order_id)
    if not expected_revision or expected_revision != context['revision']:
        raise PreconditionFailed('工价、报工、领料或已处理数量已变化，请刷新后重试。')
    if not isinstance(requested, dict) or not requested:
        raise ValidationError({'detail': '至少选择一个管材部位。'})
    quantities = {}
    for key, quantity in requested.items():
        key = str(key)
        if key in quantities:
            raise ValidationError({'detail': '同一部位不能重复申请额度，请先合并本次数量。'})
        row = context['components'].get(key)
        if not row or not row['basis_ready']:
            raise ValidationError({'detail': '部位不属于当前BOM或报工依据不完整，请刷新并核对资料。'})
        try:
            quantity = whole_pieces(quantity, '本次处理')
        except TubeQuantityError as exc:
            raise ValidationError({'detail': str(exc)}) from exc
        if quantity <= 0 or quantity > row['allowance']['remaining']:
            raise ValidationError({'detail': f'“{row["part_name"]}”最多可处理{row["allowance"]["remaining"]}支。'})
        quantities[key] = quantity
    # 未来版审批时可能还没有产出。审批后新入库/预留也不能借旧版报工，
    # 在新版自动生效时让已占用数量失去依据。
    for as_of in _basis_dates(product_line_id):
        if str(as_of) == context['as_of']:
            continue
        future = metal_component_limits(product, as_of=as_of, exclude_tube_order_id=exclude_tube_order_id)
        for key, quantity in quantities.items():
            row = future['components'].get(key)
            if (not row or not row['basis_ready'] or row['allowance']['reported_minimum']
                    < row['allowance']['report_protected_usage'] + quantity):
                raise ValidationError({'detail': f'{as_of}的已批准工价依据不能覆盖本次处理数量，请先核对工价方案。'})
    return context
