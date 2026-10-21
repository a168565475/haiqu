"""车缝首次产出额度：真实报工按稳定工项归集，直发与首次入库共用占用。"""
from collections import defaultdict
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation

from django.db.models import Q, Sum
from django.utils import timezone
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionFailed
from apps.material_issues.processing_selectors import digest
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_tasks.models import ProductionTaskProduct
from apps.workshop_config.models import Craft
from apps.workshop_reporting.models import WageScheme, WageSchemeLine, WorkReportLine
from .models import InternalSemiFinishedReceiptLine, PublicStockMovement
from .tube_processing_services import lock_tube_product_scope


def lock_sewing_product_scope(product_line_id):
    """沿用领料→排产→任务→产品的锁序；必须先于单据、工价、报工行锁。"""
    return lock_tube_product_scope(product_line_id)


def is_sewing_craft_scope(product_line_id, craft_id):
    return Craft.objects.filter(pk=craft_id, craft_type='INTERNAL', plan_category='SEWING').exists() or (
        ProductionScheduleProductCraft.objects.filter(
            schedule_product__product_line_id=product_line_id, craft_id=craft_id,
            craft_type_snapshot='INTERNAL', plan_category='SEWING',
        ).exists()
    )


def _sewing_schemes(product_line_id):
    craft_ids = ProductionScheduleProductCraft.objects.filter(
        schedule_product__product_line_id=product_line_id,
        craft_type_snapshot='INTERNAL', plan_category='SEWING',
    ).values('craft_id')
    return WageScheme.objects.filter(product_line_id=product_line_id, scope_craft__craft_type='INTERNAL').filter(
        Q(scope_craft_id__in=craft_ids) | Q(scope_craft__plan_category='SEWING'))


def sewing_output_usage(product_line_id, *, exclude_tube_order_id=None):
    """累计首次产出，不读取剩余库存；新裁片外发回货不重复占用，直发或首次入库已占。"""
    from apps.outsourcing.models import TubeOutsourcingLine
    usage = defaultdict(lambda: dict(received=0, dispatched=0, reserved=0))
    direct = TubeOutsourcingLine.objects.filter(
        order__product_line_id=product_line_id, order__source_kind='SEWING')
    if exclude_tube_order_id:
        direct = direct.exclude(order_id=exclude_tube_order_id)
    for statuses, field in [(['PENDING_DISPATCH'], 'reserved'), (['PROCESSING', 'COMPLETED'], 'dispatched')]:
        for row in direct.filter(order__status__in=statuses).values('component_identity').annotate(total=Sum('quantity')):
            usage[str(row['component_identity'])][field] += row['total']
    for row in InternalSemiFinishedReceiptLine.objects.filter(
        receipt__schedule_product__product_line_id=product_line_id, receipt__plan_category='SEWING',
    ).values('component_identity').annotate(total=Sum('quantity')):
        usage[str(row['component_identity'])]['received'] += row['total']
    for row in PublicStockMovement.objects.filter(
        product_line_id=product_line_id, direction='IN', balance__quality='AVAILABLE',
        source_type='OUTSOURCING_RETURN', balance__identity_snapshot__completed_craft__code='SEWING',
    ).values('bom_line__component_identity').annotate(total=Sum('quantity')):
        usage[str(row['bom_line__component_identity'])]['received'] += row['total']
    return usage


def _whole(value, label):
    if isinstance(value, (bool, float)):
        raise ValueError(f'{label}必须为非负整数。')
    try:
        number = Decimal(value)
    except (TypeError, ValueError, InvalidOperation) as exc:
        raise ValueError(f'{label}缺少可靠的整数依据。') from exc
    if not number.is_finite() or number < 0 or number != number.to_integral_value() or number > 99_999_999_999_999:
        raise ValueError(f'{label}必须为范围内的非负整数。')
    return int(number)


def sewing_component_limits(product_line, *, as_of=None, exclude_tube_order_id=None):
    if not isinstance(product_line, ProductionTaskProduct):
        product_line = ProductionTaskProduct.objects.get(pk=product_line)
    as_of = as_of or timezone.localdate()
    usage = sewing_output_usage(product_line.pk, exclude_tube_order_id=exclude_tube_order_id)
    bom = Bom.objects.filter(product_line=product_line, archived_at__isnull=True).order_by('-version_number', '-pk').first()
    bom_ready = bom is not None and bom.status == 'VERIFIED' and bom.order_quantity == product_line.quantity
    components = defaultdict(list)
    for line in BomLine.objects.filter(section__bom=bom, section__section_type='FABRIC', section__title='裁剪明细'):
        components[str(line.component_identity)].append(line)
    approved = list(_sewing_schemes(product_line.pk).filter(status='APPROVED').order_by('pk'))
    schemes = [scheme for scheme in approved if scheme.effective_from and scheme.effective_from <= as_of
               and (scheme.effective_to is None or scheme.effective_to >= as_of)]
    active = list(WageSchemeLine.objects.filter(scheme__in=schemes, status='ACTIVE')
                  .select_related('work_item__unit', 'scheme'))
    operations = defaultdict(list)
    for line in active:
        operations[str(line.bom_component_identity_snapshot)].append(line)
    reports = defaultdict(list)
    for row in WorkReportLine.objects.filter(
        report__product_line=product_line, report__production_date__lte=as_of,
        work_item_id__in=[line.work_item_id for line in active],
    ).select_related('scheme_line', 'report'):
        reports[row.work_item_id].append(row)
    result = {}
    for key in sorted(set(components) | set(usage)):
        lines, blockers, evidence, totals = components.get(key, []), [], [], []
        part = lines[0].part_name if len(lines) == 1 else key
        required = 0
        if not bom_ready or len(lines) != 1:
            blockers.append('请先确认与订单数量一致、部位唯一的最新 BOM。')
        else:
            try:
                required = _whole(product_line.quantity * lines[0].cutting_sets_per_product, '部位订单需求')
                if not required:
                    raise ValueError('部位订单需求必须大于零。')
            except (ValueError, TypeError) as exc:
                blockers.append(str(exc))
        rows = operations.get(key, [])
        if not rows or 'None' in operations:
            blockers.append('部位缺少有效车缝工价工序，不能用人工完成量代替报工。')
        seen = set()
        for line in rows:
            item, total, pieces_per_set = line.work_item, 0, None
            identity = (item.craft_id, item.operation_id)
            operation_errors = []
            if (identity in seen or item.product_line_id != product_line.pk
                    or item.bom_component_identity != line.bom_component_identity_snapshot
                    or item.craft_id != line.scheme.scope_craft_id or item.workshop_id != line.scheme.workshop_id
                    or item.counting_mode != line.counting_mode or line.counting_mode not in {'SET', 'PIECE'}):
                operation_errors.append('车缝工项、部位或计数方式不能唯一对应。')
            seen.add(identity)
            try:
                expected_unit = '套' if line.counting_mode == 'SET' else '片'
                unit_names = [line.unit_name_snapshot, item.unit.unit_name if item.unit_id else '']
                if any(name.strip() and name.strip() != expected_unit for name in unit_names):
                    raise ValueError('车缝工项单位与按套/按片计数方式冲突。')
                if line.counting_mode == 'PIECE':
                    pieces_per_set = _whole(line.bom_pieces_per_set_snapshot, '冻结每套片数')
                    if not pieces_per_set:
                        raise ValueError('按片报工缺少可靠的冻结每套片数。')
                    if len(lines) != 1 or pieces_per_set != _whole(lines[0].cutting_pieces_per_set, '当前裁片每套片数'):
                        raise ValueError('冻结每套片数与当前裁片实物属性冲突，请先核对来源，不能重新换算历史。')
                for report_line in reports[item.pk]:
                    frozen = report_line.scheme_line
                    if (frozen.work_item_id != item.pk or frozen.bom_component_identity_snapshot != line.bom_component_identity_snapshot
                            or frozen.counting_mode != line.counting_mode
                            or report_line.report.scheme_id != frozen.scheme_id
                            or (report_line.unit_name_snapshot.strip() and report_line.unit_name_snapshot.strip() != expected_unit)):
                        raise ValueError('历史报工工项、部位或计数单位与当前工序不一致。')
                    if line.counting_mode == 'PIECE' and _whole(frozen.bom_pieces_per_set_snapshot, '历史冻结每套片数') != pieces_per_set:
                        raise ValueError('历史报工每套片数缺失或存在冲突，不能使用当前 BOM 猜补。')
                    total += _whole(report_line.quantity, '实际报工数量')
                completed = total if line.counting_mode == 'SET' else total // pieces_per_set
                if total and not completed:
                    raise ValueError('按片报工数量不足一整套，不能直发。')
                totals.append(completed)
            except (ValueError, TypeError) as exc:
                operation_errors.append(str(exc))
                completed = 0
            blockers.extend(operation_errors)
            evidence.append(dict(work_item_id=str(item.pk), operation_id=str(item.operation_id),
                name=line.operation_name_snapshot, scheme_id=str(line.scheme_id), scheme_number=line.scheme.scheme_number,
                scheme_version=line.scheme.version, scheme_revision=line.scheme.revision, counting_mode=line.counting_mode,
                quantity=str(total), completed_sets=completed, pieces_per_set=pieces_per_set))
        values, allowance = usage[key], None
        try:
            values = {name: _whole(value, name) for name, value in values.items()}
            used, reported = sum(values.values()), min(totals) if totals else 0
            if used > required:
                blockers.append('累计首次入库、已直发和待发预留超过订单需求，请核对历史占用。')
            if used > reported:
                blockers.append('累计首次入库、已直发和待发预留超过有效报工完成套数，请核对报工及历史占用。')
            if not blockers:
                allowance = dict(required=required, reported_minimum=reported, **values, used=used,
                    remaining=max(0, min(required, reported) - used), report_protected_usage=used)
        except ValueError as exc:
            blockers.append(str(exc))
        result[key] = dict(component_identity=key, part_name=part, required=required,
            basis_ready=not blockers, blockers=list(dict.fromkeys(blockers)), operations=evidence,
            usage={name: str(value) for name, value in values.items()}, allowance=allowance)
    revision = digest(dict(product_line_id=str(product_line.pk), as_of=str(as_of), bom_id=str(bom.pk) if bom else None,
        components=result, approved_versions=[(str(row.pk), row.revision, str(row.effective_from), str(row.effective_to)) for row in approved]))
    return dict(product_line_id=str(product_line.pk), as_of=str(as_of), revision=revision, components=result)


def _basis_dates(product_line_id):
    today, dates = timezone.localdate(), {timezone.localdate()}
    for start, end in _sewing_schemes(product_line_id).filter(status='APPROVED').values_list('effective_from', 'effective_to'):
        if start and start > today:
            dates.add(start)
        if end and today <= end < date.max:
            dates.add(end + timedelta(days=1))
    return sorted(dates)


def assert_sewing_reports_cover_usage(product_line_id):
    """仅已有直发或预留时保护总占用，不给旧车缝入库新增报工前置条件。"""
    protected = {key: sum(row.values()) for key, row in sewing_output_usage(product_line_id).items()
                 if row['dispatched'] or row['reserved']}
    for as_of in _basis_dates(product_line_id) if protected else []:
        context = sewing_component_limits(product_line_id, as_of=as_of)
        for key, used in protected.items():
            row = context['components'].get(key)
            if not row or not row['basis_ready'] or row['allowance']['reported_minimum'] < used:
                raise ValidationError({'detail': f'{as_of}的裁片报工依据不足，已有{used}套首次入库、直发或预留，不能保存该变更。'})


def assert_sewing_quantity_available(*, product_line_id, requested, expected_revision, exclude_tube_order_id=None):
    product = lock_sewing_product_scope(product_line_id)
    context = sewing_component_limits(product, exclude_tube_order_id=exclude_tube_order_id)
    if not expected_revision or context['revision'] != expected_revision:
        raise PreconditionFailed('工价、报工或首次产出占用已变化，请刷新后重试。')
    if not isinstance(requested, dict) or not requested:
        raise ValidationError({'detail': '至少选择一个裁片部位。'})
    for as_of in _basis_dates(product_line_id):
        basis = context if str(as_of) == context['as_of'] else sewing_component_limits(
            product, as_of=as_of, exclude_tube_order_id=exclude_tube_order_id)
        for key, quantity in requested.items():
            row = basis['components'].get(str(key))
            try:
                quantity = _whole(quantity, '本次直发套数')
            except ValueError as exc:
                raise ValidationError({'detail': str(exc)}) from exc
            if not row or not row['basis_ready']:
                raise ValidationError({'detail': '裁片不属于当前 BOM 或报工依据不完整，请刷新并核对资料。'})
            if quantity <= 0 or quantity > row['allowance']['remaining']:
                raise ValidationError({'detail': f'“{row["part_name"]}”在{as_of}最多可直发{row["allowance"]["remaining"]}套。'})
    return context
