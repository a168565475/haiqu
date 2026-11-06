"""生产采购跟踪只读投影；按稳定来源汇总，不加载合同、图片或逐次收货明细。"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, localcontext
from uuid import UUID

from django.db.models import Count, F, OuterRef, Prefetch, Q, Subquery, Sum
from rest_framework.exceptions import ValidationError

from apps.boms.catalog_selection import SECTION_CATEGORIES
from apps.boms.material_flow_calculations import MaterialFlowValueError, pipe_plan_for_line
from apps.boms.models import Bom, BomSection
from apps.inventory.models import MaterialInboundLine
from apps.material_catalog.saved_selection import validate_saved_material
from apps.production_scheduling.models import ProductionScheduleProduct
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.material_identity import DIRECT_RAW_MATERIAL_SOURCE_KEYS, REFERENCE_MAPPING_MODELS
from apps.products.models import RawMaterialInformation

from .models import PurchaseGroup, PurchaseGroupLine, PurchaseOrderLine, SupplierPurchaseSheet
from .material_attribute_snapshot import build_material_attribute_snapshot
from .services import _is_purchasable_bom_section, _source_quantity
from .tracking_rules import BEIJING, arrival_risks, beijing_today, coverage_risks, decimal_value, quantity_text, root_count_value
from .tracking_deadlines import coverage_timing
from .tracking_policy import get_tracking_policy


VALID_PURCHASE_STATUSES = ('SUBMITTED', 'PURCHASING', 'COMPLETED')
TERMINAL_TASK_STATUSES = ('COMPLETED', 'CANCELLED')
LINE_IDENTITY_FIELDS = ('id', 'purchase_order_id', 'source_bom_line_id_snapshot', 'product_line_id_snapshot',
    'source_unit_text', 'section_type_snapshot', 'material_catalog_id', 'material_selection_snapshot',
    'calculation_snapshot', 'raw_material_snapshot', 'raw_bar_length_m', 'actual_bar_count',
    'actual_purchase_quantity', 'purchase_group_line_id')


def _uuid(value):
    try:
        return UUID(str(value)) if value else None
    except (ValueError, TypeError):
        return None


def _materials(snapshots, bom_lines=()):
    ids, numbers = set(), set()
    references = defaultdict(set)
    for snapshot in snapshots:
        if not isinstance(snapshot, dict):
            continue
        calculation = snapshot.get('calculation_snapshot') or {}
        if isinstance(calculation, dict) and _uuid(calculation.get('raw_material_id')):
            ids.add(_uuid(calculation['raw_material_id']))
        elif isinstance(snapshot.get('raw_material_snapshot'), str) and snapshot['raw_material_snapshot']:
            numbers.add(snapshot['raw_material_snapshot'])
    for line in bom_lines:
        raw = line.raw_values if isinstance(line.raw_values, dict) else {}
        for key in DIRECT_RAW_MATERIAL_SOURCE_KEYS:
            if _uuid(raw.get(key)):
                ids.add(_uuid(raw[key]))
        for key in REFERENCE_MAPPING_MODELS:
            if _uuid(raw.get(key)):
                references[key].add(_uuid(raw[key]))
    mappings = {}
    for key, model in REFERENCE_MAPPING_MODELS.items():
        if references[key]:
            for mapping_id, material_id in model.objects.filter(pk__in=references[key], archived_at__isnull=True).values_list('id', 'inventory_raw_material_id'):
                mappings[(key, str(mapping_id))] = material_id
                if material_id:
                    ids.add(material_id)
    records = list(RawMaterialInformation.objects.filter(Q(pk__in=ids) | Q(material_number__in=numbers))
                   .select_related('unit', 'category')) if ids or numbers else []
    by_number = defaultdict(list)
    for material in records:
        by_number[material.material_number].append(material)
    return {str(material.pk): material for material in records}, by_number, mappings


def _identity(snapshot, materials):
    """历史材料允许按已存编号精确唯一匹配，绝不按当前BOM/名称补身份。"""
    if not isinstance(snapshot, dict):
        return None, ['保存的采购来源格式待核对']
    unit = str(snapshot.get('source_unit_text') or '').strip()
    section = snapshot.get('section_type_snapshot')
    notes = []
    if not unit:
        notes.append('采购来源单位缺失')
    if snapshot.get('material_catalog_id'):
        try:
            selected = validate_saved_material(snapshot.get('material_selection_snapshot'),
                material_catalog_id=snapshot['material_catalog_id'])
        except ValidationError:
            return None, notes + ['保存的材料目录身份待核对']
        expected_unit = '米' if section == 'PROFILE' else selected['unit_name']
        if unit != expected_unit or section == 'PROFILE' and selected['unit_name'] != '根':
            notes.append('保存材料与采购单位不一致')
        return ('catalog', str(snapshot['material_catalog_id']), selected), notes
    calculation = snapshot.get('calculation_snapshot')
    if not isinstance(calculation, dict):
        return None, notes + ['保存的材料身份格式待核对']
    if 'raw_material_id' in calculation:
        material = materials[0].get(str(_uuid(calculation.get('raw_material_id'))))
    else:
        number = snapshot.get('raw_material_snapshot')
        if not isinstance(number, str) or not number:
            return None, notes + ['保存的历史材料编号缺失或格式待核对']
        matches = materials[1].get(number, [])
        material = matches[0] if len(matches) == 1 else None
    if material is None or material.archived_at or material.item_type != 'MATERIAL':
        return None, notes + ['历史材料身份无法唯一核实']
    if calculation.get('unit_id') and str(calculation['unit_id']) != str(material.unit_id):
        notes.append('保存材料单位身份不一致')
    if section == 'PROFILE':
        if unit != '米' or material.unit.unit_name != '根' or material.category.category_name != '管材':
            notes.append('管材根米单位或材料分类待核对')
    elif unit not in {material.unit.unit_name, material.unit.unit_code}:
        notes.append('材料与采购单位不一致')
    return ('raw', str(material.pk)), notes


def _snapshot(line):
    return {'material_catalog_id': line.material_catalog_id, 'material_selection_snapshot': line.material_selection_snapshot,
        'calculation_snapshot': line.calculation_snapshot, 'raw_material_snapshot': line.raw_material_snapshot,
        'source_unit_text': line.source_unit_text, 'section_type_snapshot': line.section_type_snapshot}


def _classification(snapshot):
    section = snapshot.get('section_type_snapshot')
    selected = snapshot.get('material_selection_snapshot') or {}
    category = selected.get('category_key') if isinstance(selected, dict) else None
    if section == 'PROFILE':
        return True if category in (None, 'TUBE') else None
    if category == 'TUBE':
        return None
    if section in {'ACCESSORY', 'FABRIC'} or category in {'HARDWARE', 'PLASTIC', 'PACKAGING', 'FABRIC', 'AUXILIARY'}:
        return False
    return None


def _common(task, product_id, product_name, material, specification, unit, group_id, source_id, row_key, evaluated_at):
    return {'row_key': row_key, 'production_task_id': str(task.pk), 'task_number': task.task_number,
        'product_line_id': str(product_id) if product_id else None, 'product_name': product_name,
        'material_name': material, 'specification': specification, 'unit': unit if isinstance(unit, str) and unit else None,
        'purchase_group_id': str(group_id) if group_id else None,
        'source_bom_line_id': str(source_id) if source_id else None,
        'source_reliable': True, 'verification_notes': [], 'is_history': False,
        'actions': [], 'action_blocked_reason': '', 'evaluated_at': evaluated_at}


def _receipt_summaries(line_ids):
    confirmed = Q(inbound__status='CONFIRMED')
    pending = Q(inbound__status='PENDING_QUALITY')
    returned = Q(return_quantity__gt=0) | Q(purchase_return_line__isnull=False)
    bad_return = (Q(purchase_return_line__isnull=True)
        | ~Q(purchase_return_line__quantity=F('return_quantity'))
        | ~Q(purchase_return_line__return_order__purchase_order_id=F('purchase_order_line__purchase_order_id'))
        | ~Q(purchase_return_line__return_order__inbound_id=F('inbound_id'))
        | ~Q(purchase_return_line__return_order__status='COMPLETED'))
    records = MaterialInboundLine.objects.filter(purchase_order_line_id__in=line_ids).order_by().values(
        'purchase_order_line_id', 'source_unit_text_snapshot', 'raw_material_information_id',
        'material_catalog_id', 'measurement_kind', 'raw_bar_length_m').annotate(
        received=Sum('received_quantity'), accepted=Sum('accepted_quantity', filter=confirmed, default=0),
        pending=Sum('received_quantity', filter=pending, default=0),
        returned=Sum('return_quantity', filter=confirmed, default=0),
        received_roots=Sum('received_bar_count'), missing_roots=Count('id', filter=Q(received_bar_count__isnull=True)),
        return_pending=Count('id', filter=confirmed & returned & bad_return),
        bad_owner=Count('id', filter=~Q(inbound__purchase_order_id=F('purchase_order_line__purchase_order_id'))),
        bad_selection=Count('id', filter=Q(material_catalog_id__isnull=False)
                            & ~Q(material_selection_snapshot=F('purchase_order_line__material_selection_snapshot'))))
    result = defaultdict(list)
    for record in records:
        result[record['purchase_order_line_id']].append(record)
    return result


def arrival_rows(*, task_ids=None, today=None, include_history=False):
    today = today or beijing_today()
    evaluated_at = datetime.now(BEIJING).isoformat()
    queryset = PurchaseOrderLine.objects.filter(purchase_order__source_type='PRODUCTION',
        purchase_order__production_task__isnull=False, purchase_order__status__in=VALID_PURCHASE_STATUSES)
    if task_ids is not None:
        queryset = queryset.filter(purchase_order__production_task_id__in=task_ids)
    if not include_history:
        # 已完成但尚有退货待处理的旧数据仍需显示，之后按聚合结果筛除普通历史。
        queryset = queryset.filter(Q(purchase_order__archived_at__isnull=True)
            | Q(material_inbound_lines__return_quantity__gt=0))
    lines = list(queryset.select_related('purchase_order__production_task').only(*LINE_IDENTITY_FIELDS,
        'product_name_snapshot', 'part_name_snapshot', 'material_snapshot', 'specification_snapshot', 'material_attributes_snapshot',
        'delivery_date', 'supplier_id', 'supplier_name_snapshot', 'purchase_order__status',
        'purchase_order__archived_at', 'purchase_order__order_number', 'purchase_order__batch_number',
        'purchase_order__purchase_group_id', 'purchase_order__production_task_id',
        'purchase_order__production_task__id', 'purchase_order__production_task__task_number',
        'purchase_order__production_task__archived_at').order_by('id').distinct())
    materials = _materials([_snapshot(line) for line in lines])
    receipts = _receipt_summaries([line.pk for line in lines])
    publications = defaultdict(list)
    for sheet in SupplierPurchaseSheet.objects.filter(purchase_order_id__in={line.purchase_order_id for line in lines},
            is_current=True, archived_at__isnull=True).values('purchase_order_id', 'supplier_id', 'status'):
        publications[(sheet['purchase_order_id'], sheet['supplier_id'])].append(sheet['status'])
    rows = []
    with localcontext() as context:
        context.prec = 64
        for line in lines:
            order = line.purchase_order
            snapshot = _snapshot(line)
            identity, notes = _identity(snapshot, materials)
            ordered = decimal_value(line.actual_purchase_quantity)
            if ordered is None or ordered == 0:
                notes.append('采购数量待核对')
            received = accepted = pending = returned = Decimal('0')
            received_roots = Decimal('0')
            return_pending = False
            receipt_valid = True
            root_valid = root_count_value(line.actual_bar_count) is not None and line.raw_bar_length_m is not None and line.raw_bar_length_m > 0
            if root_valid and ordered != line.actual_bar_count * line.raw_bar_length_m:
                root_valid = False
            for record in receipts.get(line.pk, []):
                matches = (record['source_unit_text_snapshot'] == line.source_unit_text and not record['bad_owner']
                           and not record['bad_selection'])
                if identity and identity[0] == 'raw':
                    matches &= not record['material_catalog_id'] and str(record['raw_material_information_id']) == identity[1]
                elif identity:
                    matches &= str(record['material_catalog_id']) == identity[1]
                if not matches:
                    receipt_valid = False
                received += record['received']
                accepted += record['accepted']
                pending += record['pending']
                returned += record['returned']
                return_pending |= bool(record['return_pending'])
                root_valid &= (record['measurement_kind'] == 'PIPE' and record['raw_bar_length_m'] == line.raw_bar_length_m
                               and not record['missing_roots'])
                if record['received_roots'] is not None:
                    received_roots += record['received_roots']
            if not receipt_valid:
                notes.append('到货记录的材料、单位或采购归属待核对')
                received = accepted = pending = returned = None
            unreceived = max(ordered - received, Decimal('0')) if ordered is not None and received is not None else None
            is_pipe = _classification(snapshot)
            root_note = ''
            if is_pipe and (not root_valid or not receipt_valid):
                root_note = '根数或根长依据不完整，根数待核对；已核实米数仍按米显示'
                notes.append(root_note)
            history = bool(order.archived_at or order.status == 'COMPLETED')
            if history and not include_history and not return_pending:
                continue
            row = _common(order.production_task, line.product_line_id_snapshot, line.product_name_snapshot,
                line.part_name_snapshot or line.material_snapshot or line.raw_material_snapshot, line.specification_snapshot,
                line.source_unit_text, order.purchase_group_id, line.source_bom_line_id_snapshot, str(line.pk), evaluated_at)
            statuses = publications.get((order.pk, line.supplier_id), [])
            publication = '已发布' if statuses and all(value == 'PUBLISHED' for value in statuses) else '待发布' if statuses else '未生成采购表'
            row.update(source_reliable=not notes, verification_notes=notes, is_history=history,
                purchase_order_id=str(order.pk), purchase_order_line_id=str(line.pk), purchase_order_no=order.order_number,
                batch_number=order.batch_number, publication_status=publication, supplier_name=line.supplier_name_snapshot,
                material_selection_snapshot=line.material_selection_snapshot if isinstance(line.material_selection_snapshot, dict) else {},
                material_attributes_snapshot=line.material_attributes_snapshot if isinstance(line.material_attributes_snapshot, dict) else {},
                part_name=line.part_name_snapshot, material=line.material_snapshot, raw_material=line.raw_material_snapshot,
                ordered_quantity=quantity_text(ordered), received_quantity=quantity_text(received), accepted_quantity=quantity_text(accepted),
                pending_quality_quantity=quantity_text(pending), unreceived_quantity=quantity_text(unreceived),
                return_quantity=quantity_text(returned), return_pending=return_pending,
                delivery_date=line.delivery_date.isoformat() if line.delivery_date else None,
                days_remaining=(line.delivery_date-today).days if line.delivery_date else None,
                ordered_root_count=str(line.actual_bar_count) if is_pipe and root_valid and receipt_valid else None,
                received_root_count=quantity_text(received_roots) if is_pipe and root_valid and receipt_valid else None,
                unreceived_root_count=quantity_text(max(Decimal(line.actual_bar_count)-received_roots, Decimal('0')))
                    if is_pipe and root_valid and receipt_valid else None, root_count_note=root_note,
                risks=arrival_risks(status=order.status, archived=bool(order.archived_at), unreceived=unreceived,
                    delivery_date=line.delivery_date, is_pipe=is_pipe, today=today, return_pending=return_pending,
                    source_reliable=not notes))
            detail_accessible = not order.archived_at and not order.production_task.archived_at
            if detail_accessible:
                row['actions'] = [{'kind': 'view_order', 'label': '查看批次', 'path': f'/purchase-orders/{order.pk}/details'}]
            else:
                row['action_blocked_reason'] = '单据或任务已归档，现有办理入口不可用'
            if return_pending and detail_accessible:
                row['actions'].append({'kind': 'view_return', 'label': '查看退货', 'path': f'/purchase-return-records?purchase_order_id={order.pk}&from=orders'})
            rows.append(row)
    return rows


def _bom_snapshot(line, bom, materials):
    notes = []
    raw = line.raw_values if isinstance(line.raw_values, dict) else {}
    material_id = None
    for key in DIRECT_RAW_MATERIAL_SOURCE_KEYS:
        if raw.get(key):
            material_id = raw[key]
            break
    if not material_id:
        for key in REFERENCE_MAPPING_MODELS:
            if raw.get(key):
                material_id = materials[2].get((key, str(raw[key])))
                break
    if not material_id and not line.material_catalog_id:
        notes.append('当前BOM没有已保存的材料身份关联')
    snapshot = {'material_catalog_id': line.material_catalog_id, 'material_selection_snapshot': line.material_selection_snapshot,
        'calculation_snapshot': {'raw_material_id': str(material_id)} if material_id else {},
        'raw_material_snapshot': line.raw_material, 'section_type_snapshot': line.section.section_type,
        'section_title_snapshot': line.section.title,
        'source_unit_text': '米' if line.section.section_type == 'PROFILE' else line.unit,
        'part_name_snapshot': line.part_name, 'material_snapshot': line.material, 'specification_snapshot': line.specification,
        'material_attributes_snapshot': build_material_attribute_snapshot(line, line.section)
            if isinstance(line.raw_values, dict) else {},
        'raw_bar_length_m': line.raw_bar_length_m, 'suggested_bar_count': line.suggested_bar_count}
    identity, identity_notes = _identity(snapshot, materials)
    notes.extend(identity_notes)
    if not isinstance(line.raw_values, dict):
        required = None
        notes.append('BOM计算依据格式待核对')
    elif line.section.section_type == 'PROFILE':
        try:
            plan = pipe_plan_for_line(line)
            snapshot['calculation_snapshot'].update(plan)
            required = decimal_value(plan['suggested_purchase_meters'])
            if (decimal_value(plan['raw_bar_length_m']) != line.raw_bar_length_m
                    or plan['suggested_bar_count'] != line.suggested_bar_count or required != line.suggested_purchase_meters):
                notes.append('管材计算参数与保存结果不一致')
        except MaterialFlowValueError:
            required = None
            notes.append('管材计算依据缺失')
    else:
        required, _field, _text, unit, parsed = _source_quantity(line, bom)
        snapshot['source_unit_text'] = unit
        if parsed != 'READY':
            notes.append('BOM需求量未识别')
    required = decimal_value(required)
    if required is None or required <= 0:
        notes.append('BOM需求数量待核对')
    snapshot['required_quantity'] = required
    return snapshot, identity, notes


def _semantic(snapshot, identity):
    calculation = snapshot.get('calculation_snapshot') or {}
    if not isinstance(calculation, dict):
        calculation = {}
    pipe_basis = tuple(decimal_value(calculation.get(key)) for key in (
        'cutting_length_mm', 'pieces_per_product', 'pieces_per_bar', 'order_quantity'))
    return (identity, decimal_value(snapshot.get('required_quantity')), snapshot.get('source_unit_text'),
            decimal_value(snapshot.get('raw_bar_length_m')), decimal_value(snapshot.get('suggested_bar_count')), pipe_basis)


def _coverage_category(snapshot):
    # 使用已保存的分类或固定 BOM 分区，不按材料名称猜分类。
    selected = snapshot.get('material_selection_snapshot')
    selected_key = selected.get('category_key') if isinstance(selected, dict) else None
    section_key = SECTION_CATEGORIES.get(str(snapshot.get('section_title_snapshot') or '').strip())
    if selected_key:
        return selected_key if selected_key in SECTION_CATEGORIES.values() and (
            section_key is None or selected_key == section_key) else None
    return section_key


def _coverage_details(task, bom, snapshot=None):
    """展示沿用该行采购来源，不用当前 BOM 覆盖已冻结的物料属性。"""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    selected = snapshot.get('material_selection_snapshot')
    attributes = snapshot.get('material_attributes_snapshot')
    return {
        'bom_created_at': bom.created_at.isoformat() if bom else None,
        'bom_confirmed_at': bom.confirmed_at.isoformat() if bom and bom.status == 'VERIFIED' and bom.confirmed_at else None,
        'bom_purchase_due_at': None,
        'latest_purchase_date': None,
        'purchase_days_remaining': None,
        'material_category_key': _coverage_category(snapshot),
        'order_delivery_date': task.delivery_date.isoformat() if task.delivery_date else None,
        'material_selection_snapshot': selected if isinstance(selected, dict) else {},
        'material_attributes_snapshot': attributes if isinstance(attributes, dict) else {},
        'part_name': str(snapshot.get('part_name_snapshot') or ''),
        'material': str(snapshot.get('material_snapshot') or ''),
        'raw_material': str(snapshot.get('raw_material_snapshot') or ''),
    }


def coverage_rows(*, task_ids=None, today=None, now=None, include_history=False):
    now = now or datetime.now(BEIJING)
    evaluated_at = now.isoformat()
    policy = get_tracking_policy()
    task_query = ProductionTask.objects.exclude(status__in=['DRAFT', 'PENDING_VALIDATION'])
    if task_ids is not None:
        task_query = task_query.filter(pk__in=task_ids)
    if not include_history:
        task_query = task_query.filter(archived_at__isnull=True).exclude(status__in=TERMINAL_TASK_STATUSES)
    tasks = {task.pk: task for task in task_query.only('id', 'task_number', 'status', 'archived_at', 'accepted_by_employee_id', 'started_at', 'delivery_date')}
    latest = Bom.objects.filter(product_line_id=OuterRef('pk'), archived_at__isnull=True).order_by('-version_number', '-id')
    products = list(ProductionTaskProduct.objects.filter(production_task_id__in=tasks).annotate(
        tracking_bom_id=Subquery(latest.values('id')[:1])).only('id', 'production_task_id', 'product_name_snapshot', 'quantity', 'line_number'))
    product_ids_by_task = defaultdict(set)
    for product in products:
        product_ids_by_task[product.production_task_id].add(product.pk)
    boms = {bom.pk: bom for bom in Bom.objects.filter(pk__in=[product.tracking_bom_id for product in products if product.tracking_bom_id])
        .prefetch_related(Prefetch('sections', queryset=BomSection.objects.prefetch_related('lines')))}
    current_lines = [line for bom in boms.values() for section in bom.sections.all()
                     if _is_purchasable_bom_section(section) for line in section.lines.all()]
    groups = list(PurchaseGroup.objects.filter(production_task_id__in=tasks, archived_at__isnull=True)
        .only('id', 'production_task_id', 'product_line_id_snapshot', 'compatibility_issues', 'manual_completed_at')
        .prefetch_related(Prefetch('lines', queryset=PurchaseGroupLine.objects.only('id', 'purchase_group_id',
            'source_bom_line_id_snapshot', 'product_line_id_snapshot', 'required_quantity', 'source_snapshot', 'compatibility_issues'))))
    group_map = defaultdict(list)
    for group in groups:
        group_map[(group.production_task_id, group.product_line_id_snapshot)].append(group)
    purchase_lines = list(PurchaseOrderLine.objects.filter(purchase_order__production_task_id__in=tasks,
        purchase_order__source_type='PRODUCTION', purchase_order__archived_at__isnull=True,
        purchase_order__status__in=VALID_PURCHASE_STATUSES).select_related('purchase_order')
        .only(*LINE_IDENTITY_FIELDS, 'purchase_order__production_task_id', 'purchase_order__purchase_group_id').order_by('id'))
    purchase_map = defaultdict(list)
    for line in purchase_lines:
        purchase_map[(line.purchase_order.production_task_id, line.product_line_id_snapshot)].append(line)
    unresolved_product_tasks = {group.production_task_id for group in groups
        if group.product_line_id_snapshot not in product_ids_by_task[group.production_task_id]}
    unresolved_product_tasks.update(line.purchase_order.production_task_id for line in purchase_lines
        if line.product_line_id_snapshot not in product_ids_by_task[line.purchase_order.production_task_id])
    frozen = [line.source_snapshot for group in groups for line in group.lines.all()]
    materials = _materials([*frozen, *[_snapshot(line) for line in purchase_lines]], current_lines)
    schedules = {row['product_line_id']: row for row in ProductionScheduleProduct.objects.filter(
        product_line_id__in=[product.pk for product in products], removed_at__isnull=True,
        schedule__record_status='ACTIVE').values('product_line_id', 'material_inbound_date')}
    rows = []
    with localcontext() as context:
        context.prec = 64
        for product in products:
            task = tasks[product.production_task_id]
            history = bool(task.archived_at or task.status in TERMINAL_TASK_STATUSES)
            scheduled = not history and product.pk in schedules
            bom = boms.get(product.tracking_bom_id)
            product_notes = []
            if task.pk in unresolved_product_tasks:
                product_notes.append('历史总单或采购明细的产品归属无法核实，不能当作未采购')
            if task.status == 'PAUSED' and not task.accepted_by_employee_id and not task.started_at:
                product_notes.append('历史暂停任务的已接单来源待核对')
            if bom is None:
                product_notes.append('最新有效BOM缺失')
            elif bom.status != 'VERIFIED':
                product_notes.append('最新BOM尚未确认，不能回退旧版本')
            if bom and Decimal(bom.order_quantity) != Decimal(product.quantity):
                product_notes.append('BOM需求数量与任务产品数量不一致')
            associated = group_map.get((task.pk, product.pk), [])
            group = associated[0] if len(associated) == 1 else None
            if len(associated) > 1 or group_map.get((task.pk, None)):
                product_notes.append('采购总单产品归属不唯一')
            if group and group.compatibility_issues:
                product_notes.append('采购总单来源存在历史待核对项')
            current = {}
            if bom:
                for section in bom.sections.all():
                    if _is_purchasable_bom_section(section):
                        for line in section.lines.all():
                            current[str(line.pk)] = _bom_snapshot(line, bom, materials)
            if not current:
                product_notes.append('没有可核实的采购需求行')
            source_lines = list(group.lines.all()) if group else []
            known_sources = {str(line.source_bom_line_id_snapshot) for line in source_lines} if group else set(current)
            if any(str(line.source_bom_line_id_snapshot) not in known_sources
                   for line in purchase_map.get((task.pk, product.pk), [])):
                product_notes.append('历史采购无法核实BOM需求行归属，不能当作未采购')
            if group and set(current) != {str(line.source_bom_line_id_snapshot) for line in source_lines}:
                rows.append(_unknown_product_row(task, product, group, bom, scheduled, schedules, history,
                    product_notes + ['当前BOM行集合与冻结总单不同，需核对增补或跨版本来源'], evaluated_at,
                    changed=bool(bom and bom.status == 'VERIFIED')))
                continue
            if not group and product_notes:
                rows.append(_unknown_product_row(task, product, None, bom, scheduled, schedules, history,
                    product_notes, evaluated_at))
                continue
            entries = [(str(line.source_bom_line_id_snapshot), line.source_snapshot, line) for line in source_lines]
            if not group:
                entries = [(key, value[0], None) for key, value in current.items()]
            for source_id, snapshot, frozen_line in entries:
                notes = list(product_notes)
                identity, source_notes = _identity(snapshot, materials)
                notes.extend(source_notes)
                if not isinstance(snapshot, dict):
                    snapshot = {}
                required = decimal_value(frozen_line.required_quantity if frozen_line else snapshot.get('required_quantity'))
                if required is None or required <= 0:
                    notes.append('需求量待核对')
                changed = False
                current_source = current.get(source_id)
                if current_source:
                    notes.extend(current_source[2])
                    if (group and identity and not source_notes and bom.status == 'VERIFIED'
                            and _semantic(snapshot, identity) != _semantic(current_source[0], current_source[1])):
                        changed = True
                        notes.append('当前BOM的材料、数量、单位或管材参数已改变')
                if frozen_line and frozen_line.compatibility_issues:
                    notes.append('冻结来源行待核对')
                purchased, purchased_roots = Decimal('0'), Decimal('0')
                required_roots = root_count_value(snapshot.get('suggested_bar_count'))
                root_valid = decimal_value(snapshot.get('raw_bar_length_m')) not in (None, Decimal('0')) and required_roots is not None
                for line in purchase_map.get((task.pk, product.pk), []):
                    if str(line.source_bom_line_id_snapshot) != source_id:
                        continue
                    line_identity, line_notes = _identity(_snapshot(line), materials)
                    quantity = decimal_value(line.actual_purchase_quantity)
                    if (line_notes or line_identity != identity or line.source_unit_text != snapshot.get('source_unit_text')
                            or quantity is None or group and (line.purchase_order.purchase_group_id != group.pk
                            or line.purchase_group_line_id != frozen_line.pk)):
                        notes.append('采购批次来源身份、单位或数量与需求不一致')
                        continue
                    purchased += quantity
                    if line.actual_bar_count is None or decimal_value(line.raw_bar_length_m) != decimal_value(snapshot.get('raw_bar_length_m')):
                        root_valid = False
                    else:
                        purchased_roots += line.actual_bar_count
                if purchase_map.get((task.pk, None)):
                    notes.append('历史采购无法核实产品归属，不能当作未采购')
                is_pipe = _classification(snapshot)
                root_note = ''
                if is_pipe and not root_valid:
                    root_note = '根数或根长依据缺失，保留米数并标记根数待核对'
                    notes.append(root_note)
                reliable = not notes
                remaining = max(required - purchased, Decimal('0')) if reliable and required is not None else None
                row = _common(task, product.pk, product.product_name_snapshot,
                    snapshot.get('part_name_snapshot') or snapshot.get('material_snapshot') or snapshot.get('raw_material_snapshot') or '需求材料',
                    snapshot.get('specification_snapshot', ''), snapshot.get('source_unit_text'), group.pk if group else None,
                    source_id, f'{task.pk}:{product.pk}:{source_id}', evaluated_at)
                row.update(**_coverage_details(task, bom, snapshot),
                    source_reliable=reliable, verification_notes=list(dict.fromkeys(notes)), is_history=history,
                    required_quantity=quantity_text(required), purchased_quantity=quantity_text(purchased) if reliable else None,
                    remaining_quantity=quantity_text(remaining), scheduled=scheduled,
                    material_inbound_date=schedules[product.pk]['material_inbound_date'].isoformat() if scheduled else None,
                    group_status=('人工完成总单' if group.manual_completed_at else '已建总单') if group else '总单未建',
                    required_root_count=str(required_roots) if is_pipe and root_valid else None,
                    purchased_root_count=quantity_text(purchased_roots) if is_pipe and root_valid and reliable else None,
                    remaining_root_count=quantity_text(max(Decimal(required_roots)-purchased_roots, Decimal('0')))
                        if is_pipe and root_valid and reliable else None, root_count_note=root_note,
                    risks=coverage_risks(required=required, purchased=purchased, scheduled=scheduled, reliable=reliable,
                                         changed=changed, history=history))
                _coverage_actions(row, task, group, bom, reliable, remaining)
                rows.append(row)
    if policy is not None:
        boms_by_product = {bom.product_line_id: bom for bom in boms.values()}
        for row in rows:
            bom = boms_by_product.get(_uuid(row['product_line_id']))
            _apply_coverage_timing(row, bom, now, policy)
    return rows


def _apply_coverage_timing(row, bom, now, policy):
    if row['is_history'] or any(item['code'] == 'COVERED' for item in row['risks']):
        return
    timing = coverage_timing(now=now, bom_confirmed_at=bom.confirmed_at if bom else None,
        bom_verified=bool(bom and bom.status == 'VERIFIED'), scheduled=row['scheduled'],
        material_inbound_date=date.fromisoformat(row['material_inbound_date']) if row['material_inbound_date'] else None,
        order_delivery_date=date.fromisoformat(row['order_delivery_date']) if row['order_delivery_date'] else None,
        category_key=row['material_category_key'], policy=policy)
    timing_risks = timing.pop('timing_risks')
    if not row['source_reliable']:
        # 需求来源不明时保留日期缺失提示，不能直接断言漏采或超期。
        timing_risks = [item for item in timing_risks if item['code'].endswith('_UNKNOWN')]
    row.update(timing)
    risks = [dict(item, level='info', rank=30) if item['code'] in {
        'SCHEDULED_UNPURCHASED', 'SCHEDULED_SHORT'} else item for item in row['risks']]
    row['risks'] = sorted([*risks, *timing_risks], key=lambda item: -item['rank'])


def _coverage_actions(row, task, group, bom, reliable, remaining):
    if group and not task.archived_at:
        row['actions'].append({'kind': 'view_group', 'label': '查看总单', 'path': f'/purchase-groups/{group.pk}'})
    if bom and not reliable and not task.archived_at:
        row['actions'].append({'kind': 'view_bom', 'label': '查看BOM', 'path': f'/boms/{bom.pk}/preview'})
    if task.archived_at or task.status not in {'READY', 'IN_PRODUCTION'}:
        row['action_blocked_reason'] = '任务当前状态不允许新增采购'
    elif not reliable:
        row['action_blocked_reason'] = '请先核对需求来源，不能直接补采'
    elif remaining is not None and remaining > 0:
        if group:
            row['actions'].append({'kind': 'create_batch', 'label': '新增批次', 'path': f'/purchase-groups/{group.pk}/batches/new'})
        else:
            row['actions'].append({'kind': 'create_group', 'label': '创建总单',
                'path': f'/purchase-orders/new?production_task_id={task.pk}&bom_id={bom.pk}'})


def _unknown_product_row(task, product, group, bom, scheduled, schedules, history, notes, evaluated_at, changed=False):
    row = _common(task, product.pk, product.product_name_snapshot, '需求待核对', '', None,
        group.pk if group else None, None, f'{task.pk}:{product.pk}:unknown', evaluated_at)
    row.update(**_coverage_details(task, bom),
        source_reliable=False, verification_notes=list(dict.fromkeys(notes)), is_history=history,
        required_quantity=None, purchased_quantity=None, remaining_quantity=None, scheduled=scheduled,
        material_inbound_date=schedules[product.pk]['material_inbound_date'].isoformat() if scheduled else None,
        group_status='来源待核对', required_root_count=None, purchased_root_count=None, remaining_root_count=None, root_count_note='',
        risks=coverage_risks(required=None, purchased=None, scheduled=scheduled, reliable=False, changed=changed, history=history))
    _coverage_actions(row, task, group, bom, False, None)
    return row
