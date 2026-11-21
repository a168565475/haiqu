"""生产采购跟踪只读投影；按稳定来源汇总，不加载合同、图片或逐次收货明细。"""
from collections import defaultdict
from datetime import date, datetime
from decimal import Decimal, localcontext
from uuid import UUID

from django.db.models import Case, Count, DecimalField, F, OuterRef, Prefetch, Q, Subquery, Sum, When
from rest_framework.exceptions import ValidationError

from apps.boms.catalog_selection import SECTION_CATEGORIES
from apps.boms.material_flow_calculations import MaterialFlowValueError, pipe_plan_for_line
from apps.boms.models import Bom, BomLine, BomSection
from apps.inventory.models import MaterialInboundLine
from apps.inventory.pipe_receipt_basis import root_receipt_line_ids
from apps.material_catalog.saved_selection import validate_saved_material
from apps.material_catalog.snapshots import material_identity_key
from apps.production_scheduling.models import ProductionScheduleProduct
from apps.production_tasks.models import ProductionTask, ProductionTaskProduct
from apps.products.material_identity import DIRECT_RAW_MATERIAL_SOURCE_KEYS, REFERENCE_MAPPING_MODELS
from apps.products.models import RawMaterialInformation

from .models import PurchaseGroup, PurchaseGroupLine, PurchaseOrderLine, SupplierPurchaseSheet
from .catalog_materials import is_weight_purchase
from .material_attribute_snapshot import build_material_attribute_snapshot
from .services import _hardware_weight_data, _is_purchasable_bom_section, _source_quantity
from .tracking_rules import BEIJING, arrival_risks, beijing_today, coverage_risks, decimal_value, quantity_text, root_count_value
from .tracking_deadlines import coverage_timing
from .tracking_policy import get_tracking_policy


VALID_PURCHASE_STATUSES = ('SUBMITTED', 'PURCHASING', 'COMPLETED')
TERMINAL_TASK_STATUSES = ('COMPLETED', 'CANCELLED')
LINE_IDENTITY_FIELDS = ('id', 'purchase_order_id', 'source_bom_line_id_snapshot', 'product_line_id_snapshot',
    'source_unit_text', 'section_type_snapshot', 'material_catalog_id', 'material_selection_snapshot',
    'calculation_snapshot', 'raw_material_snapshot', 'raw_bar_length_m', 'raw_bar_weight_kg', 'actual_bar_count',
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
    calculation = snapshot.get('calculation_snapshot')
    hardware = isinstance(calculation, dict) and calculation.get('measurement_kind') == 'HARDWARE_WEIGHT'
    notes = []
    if not unit:
        notes.append('采购来源单位缺失')
    if snapshot.get('material_catalog_id'):
        try:
            selected = validate_saved_material(snapshot.get('material_selection_snapshot'),
                material_catalog_id=snapshot['material_catalog_id'])
        except ValidationError:
            return None, notes + ['保存的材料目录身份待核对']
        expected_unit = ('KG' if section == 'PROFILE' and unit == 'KG' else '米') if section == 'PROFILE' else ('KG' if hardware else selected['unit_name'])
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
        if unit not in {'米', 'KG'} or material.unit.unit_name != '根' or material.category.category_name != '管材':
            notes.append('管材采购单位或材料分类待核对')
    elif unit not in ({'KG'} if hardware else {material.unit.unit_name, material.unit.unit_code}):
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
    weight_receipt = Q(source_unit_text_snapshot='KG') & (
        Q(measurement_kind='PIPE') | Q(calculation_snapshot__measurement_kind='HARDWARE_WEIGHT'))
    returned = Q(return_quantity__gt=0) | Q(return_weight_kg__gt=0) | Q(purchase_return_line__isnull=False)
    bad_return_meter = (Q(purchase_return_line__isnull=True)
        | ~Q(purchase_return_line__quantity=F('return_quantity'))
        | ~Q(purchase_return_line__return_order__purchase_order_id=F('purchase_order_line__purchase_order_id'))
        | ~Q(purchase_return_line__return_order__inbound_id=F('inbound_id'))
        | ~Q(purchase_return_line__return_order__status='COMPLETED'))
    bad_return_weight = (Q(purchase_return_line__isnull=True)
        | ~Q(purchase_return_line__quantity=Case(
            When(calculation_snapshot__receipt_quantity_mode='ROOTS', then=F('return_bar_count')),
            default=F('return_weight_kg'), output_field=DecimalField()))
        | ~Q(purchase_return_line__return_order__purchase_order_id=F('purchase_order_line__purchase_order_id'))
        | ~Q(purchase_return_line__return_order__inbound_id=F('inbound_id'))
        | ~Q(purchase_return_line__return_order__status='COMPLETED'))
    records = MaterialInboundLine.objects.filter(purchase_order_line_id__in=line_ids).order_by().values(
        'purchase_order_line_id', 'source_unit_text_snapshot', 'raw_material_information_id',
        'material_catalog_id', 'measurement_kind', 'raw_bar_length_m', 'bar_weight_kg').annotate(
        received=Sum('received_quantity'), accepted=Sum('accepted_quantity', filter=confirmed, default=0),
        pending=Sum('received_quantity', filter=pending, default=0),
        returned=Sum('return_quantity', filter=confirmed, default=0),
        received_weight=Sum('received_weight_kg'), accepted_weight=Sum('accepted_weight_kg', filter=confirmed, default=0),
        pending_weight=Sum('received_weight_kg', filter=pending, default=0), returned_weight=Sum('return_weight_kg', filter=confirmed, default=0),
        missing_weight=Count('id', filter=Q(received_weight_kg__isnull=True)
            | (confirmed & (Q(accepted_weight_kg__isnull=True) | Q(return_weight_kg__isnull=True)))),
        received_roots=Sum('received_bar_count'), missing_roots=Count('id', filter=Q(received_bar_count__isnull=True)),
        accepted_roots=Sum('accepted_bar_count', filter=confirmed, default=0),
        pending_roots=Sum('received_bar_count', filter=pending, default=0),
        returned_roots=Sum('return_bar_count', filter=confirmed, default=0),
        return_pending_meter=Count('id', filter=confirmed & ~weight_receipt & returned & bad_return_meter),
        return_pending_weight=Count('id', filter=confirmed & weight_receipt & returned & bad_return_weight),
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
            | Q(material_inbound_lines__return_quantity__gt=0) | Q(material_inbound_lines__return_weight_kg__gt=0))
    lines = list(queryset.select_related('purchase_order__production_task').only(*LINE_IDENTITY_FIELDS,
        'product_name_snapshot', 'part_name_snapshot', 'material_snapshot', 'specification_snapshot', 'material_attributes_snapshot',
        'delivery_date', 'supplier_id', 'supplier_name_snapshot', 'purchase_order__status', 'purchase_order__source_type',
        'purchase_order__archived_at', 'purchase_order__order_number', 'purchase_order__batch_number',
        'purchase_order__purchase_group_id', 'purchase_order__production_task_id',
        'purchase_order__production_task__id', 'purchase_order__production_task__task_number',
        'purchase_order__production_task__archived_at').order_by('id').distinct())
    materials = _materials([_snapshot(line) for line in lines])
    receipts = _receipt_summaries([line.pk for line in lines])
    root_ids = root_receipt_line_ids(lines)
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
            received_weight = accepted_weight = pending_weight = returned_weight = Decimal('0')
            received_roots = Decimal('0')
            accepted_roots = pending_roots = returned_roots = Decimal('0')
            root_receipt = line.pk in root_ids
            return_pending = False
            receipt_valid = True
            weight_valid = True
            is_weight = is_weight_purchase(line)
            root_valid = (root_count_value(line.actual_bar_count) is not None
                          and (line.raw_bar_weight_kg is not None and line.raw_bar_weight_kg > 0 if is_weight and not root_receipt
                               else line.raw_bar_length_m is not None and line.raw_bar_length_m > 0))
            if root_valid and not is_weight and ordered != line.actual_bar_count * line.raw_bar_length_m:
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
                if is_weight and (record['missing_weight'] or any(decimal_value(record[key]) is None
                        for key in ('received_weight', 'accepted_weight', 'pending_weight', 'returned_weight'))):
                    weight_valid = False
                received_weight += record['received_weight'] or Decimal('0')
                accepted_weight += record['accepted_weight'] or Decimal('0')
                pending_weight += record['pending_weight'] or Decimal('0')
                returned_weight += record['returned_weight'] or Decimal('0')
                return_pending |= bool(record['return_pending_meter'] or record['return_pending_weight'])
                root_valid &= (record['measurement_kind'] == 'PIPE' and (record['bar_weight_kg'] == line.raw_bar_weight_kg if is_weight and not root_receipt else record['raw_bar_length_m'] == line.raw_bar_length_m)
                               and not record['missing_roots'])
                if record['received_roots'] is not None:
                    received_roots += record['received_roots']
                if root_receipt:
                    accepted_roots += record['accepted_roots']
                    pending_roots += record['pending_roots']
                    returned_roots += record['returned_roots']
            if not receipt_valid:
                notes.append('到货记录的材料、单位或采购归属待核对')
                received = accepted = pending = returned = None
                received_weight = accepted_weight = pending_weight = returned_weight = None
            if root_receipt:
                ordered = Decimal(line.actual_bar_count)
                received, accepted, pending, returned = (
                    (received_roots, accepted_roots, pending_roots, returned_roots)
                    if root_valid and receipt_valid else (None, None, None, None))
                received_weight = accepted_weight = pending_weight = returned_weight = None
            elif is_weight:
                if not weight_valid:
                    notes.append('到货重量缺失或无效，采购重量进度待核对')
                    received_weight = accepted_weight = pending_weight = returned_weight = None
                # 原数量列保留管材米数或五金个数，采购进度统一使用实收 KG。
                received, accepted, pending, returned = received_weight, accepted_weight, pending_weight, returned_weight
            unreceived = max(ordered - received, Decimal('0')) if ordered is not None and received is not None else None
            if root_receipt and accepted is not None:
                unreceived = max(ordered - accepted - pending, Decimal('0'))
            is_pipe = _classification(snapshot)
            root_note = ''
            if is_pipe and (not root_valid or not receipt_valid):
                if root_receipt:
                    root_note = '本批实收根数或原长待核对'
                else:
                    root_note = '根数或每根重量依据不完整，根数待核对；已核实采购重量仍按 KG 显示' if is_weight else '根数或根长依据不完整，根数待核对；已核实米数仍按米显示'
                notes.append(root_note)
            history = bool(order.archived_at or order.status == 'COMPLETED')
            if history and not include_history and not return_pending:
                continue
            contributions = line.calculation_snapshot.get('group_source_contributions', []) if isinstance(line.calculation_snapshot, dict) else []
            names = {item['product_line_id']: ' '.join(filter(None, (item['product_name'], item.get('product_color'))))
                     for item in contributions}
            row = _common(order.production_task, None if len(names) > 1 else line.product_line_id_snapshot,
                ' / '.join(names.values()) or line.product_name_snapshot,
                line.part_name_snapshot or line.material_snapshot or line.raw_material_snapshot, line.specification_snapshot,
                '根' if root_receipt else line.source_unit_text, order.purchase_group_id, line.source_bom_line_id_snapshot, str(line.pk), evaluated_at)
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
                 ordered_weight_kg=quantity_text(line.actual_purchase_quantity) if is_weight else None,
                 received_weight_kg=quantity_text(received_weight) if is_weight else None,
                 accepted_weight_kg=quantity_text(accepted_weight) if is_weight else None,
                 pending_quality_weight_kg=quantity_text(pending_weight) if is_weight else None,
                 unreceived_weight_kg=quantity_text(unreceived) if is_weight and not root_receipt else None,
                 return_weight_kg=quantity_text(returned_weight) if is_weight else None,
                delivery_date=line.delivery_date.isoformat() if line.delivery_date else None,
                days_remaining=(line.delivery_date-today).days if line.delivery_date else None,
                ordered_root_count=str(line.actual_bar_count) if is_pipe and root_valid and receipt_valid else None,
                received_root_count=quantity_text(received_roots) if is_pipe and root_valid and receipt_valid else None,
                unreceived_root_count=quantity_text(unreceived if root_receipt else max(Decimal(line.actual_bar_count)-received_roots, Decimal('0')))
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
    is_weight = line.section.section_type == 'PROFILE' and any(raw.get(key) not in (None, '') for key in (
        'long_material_unit_weight_kg', 'long_material_total_weight_kg'))
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
        'source_unit_text': 'KG' if is_weight else ('米' if line.section.section_type == 'PROFILE' else line.unit),
        'part_name_snapshot': line.part_name, 'material_snapshot': line.material, 'specification_snapshot': line.specification,
        'material_attributes_snapshot': build_material_attribute_snapshot(line, line.section)
            if isinstance(line.raw_values, dict) else {},
         'raw_bar_length_m': line.raw_bar_length_m, 'suggested_bar_count': line.suggested_bar_count}
    if not isinstance(line.raw_values, dict):
        required = None
        notes.append('BOM计算依据格式待核对')
    elif line.section.section_type == 'PROFILE':
        try:
            plan = pipe_plan_for_line(line)
            snapshot['calculation_snapshot'].update(plan)
            raw_weight = raw.get('long_material_unit_weight_kg')
            total_weight = raw.get('long_material_total_weight_kg')
            if is_weight:
                snapshot['calculation_snapshot'].update(measurement_unit='kg', raw_bar_weight_kg=str(raw_weight), suggested_purchase_weight_kg=str(total_weight))
                snapshot['raw_bar_weight_kg'] = decimal_value(raw_weight)
                required = decimal_value(total_weight)
                if snapshot['raw_bar_weight_kg'] in (None, Decimal('0')) or required in (None, Decimal('0')):
                    required = None
                    notes.append('管材长料单重或建议采购重量缺失')
                elif required != (snapshot['raw_bar_weight_kg'] * Decimal(plan['suggested_bar_count'])).quantize(Decimal('0.0001')):
                    notes.append('管材建议采购重量与根数、长料单重不一致')
            else:
                required = decimal_value(plan['suggested_purchase_meters'])
            if (decimal_value(plan['raw_bar_length_m']) != line.raw_bar_length_m
                    or plan['suggested_bar_count'] != line.suggested_bar_count
                    or decimal_value(plan['suggested_purchase_meters']) != line.suggested_purchase_meters):
                notes.append('管材计算参数与保存结果不一致')
        except MaterialFlowValueError:
            required = None
            notes.append('管材计算依据缺失')
    else:
        required, _field, _text, unit, parsed = _source_quantity(line, bom)
        snapshot['source_unit_text'] = unit
        if line.section.section_type == 'ACCESSORY' and _hardware_weight_data(line, bom) is not None:
            snapshot['calculation_snapshot']['measurement_kind'] = 'HARDWARE_WEIGHT'
        if parsed != 'READY':
            notes.append('BOM需求量未识别')
    identity, identity_notes = _identity(snapshot, materials)
    notes.extend(identity_notes)
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
            decimal_value(snapshot.get('raw_bar_length_m')), decimal_value(snapshot.get('raw_bar_weight_kg')),
            decimal_value(snapshot.get('suggested_bar_count')), pipe_basis)


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


def _coverage_material_row(task, group, bom, snapshot, *, product_id, product_name, source_id, row_key, required,
        purchases, materials, notes, changed, history, scheduled, inbound_date, evaluated_at):
    purchased, purchased_roots = Decimal('0'), Decimal('0')
    required_roots = root_count_value(snapshot.get('suggested_bar_count'))
    is_weight = snapshot.get('source_unit_text') == 'KG' and snapshot.get('section_type_snapshot') == 'PROFILE'
    root_valid = (decimal_value(snapshot.get('raw_bar_weight_kg')) not in (None, Decimal('0')) if is_weight
                  else decimal_value(snapshot.get('raw_bar_length_m')) not in (None, Decimal('0'))) and required_roots is not None
    for line, expected_identity, valid_source in purchases:
        line_identity, line_notes = _identity(_snapshot(line), materials)
        quantity = decimal_value(line.actual_purchase_quantity)
        matched = line_identity == expected_identity
        if not matched and snapshot.get('source_contributions') and line_identity and expected_identity:
            if line_identity[0] == expected_identity[0] == 'catalog':
                matched = material_identity_key(line_identity[2]) == material_identity_key(expected_identity[2])
        if (line_notes or not matched or line.source_unit_text != snapshot.get('source_unit_text')
                or quantity is None or not valid_source):
            notes.append('采购批次来源身份、单位或数量与需求不一致')
            continue
        purchased += quantity
        if line.actual_bar_count is None or (is_weight and decimal_value(line.raw_bar_weight_kg) != decimal_value(snapshot.get('raw_bar_weight_kg'))) or (not is_weight and decimal_value(line.raw_bar_length_m) != decimal_value(snapshot.get('raw_bar_length_m'))):
            root_valid = False
        else:
            purchased_roots += line.actual_bar_count
    is_pipe = _classification(snapshot)
    root_note = ''
    if is_pipe and not root_valid:
        root_note = '根数或每根重量依据缺失，保留采购量并标记根数待核对'
        notes.append(root_note)
    reliable = not notes
    remaining = max(required - purchased, Decimal('0')) if reliable and required is not None else None
    row = _common(task, product_id, product_name,
        snapshot.get('part_name_snapshot') or snapshot.get('material_snapshot') or snapshot.get('raw_material_snapshot') or '需求材料',
        snapshot.get('specification_snapshot', ''), snapshot.get('source_unit_text'), group.pk if group else None,
        source_id, row_key, evaluated_at)
    row.update(**_coverage_details(task, bom, snapshot),
        source_reliable=reliable, verification_notes=list(dict.fromkeys(notes)), is_history=history,
        required_quantity=quantity_text(required), purchased_quantity=quantity_text(purchased) if reliable else None,
        remaining_quantity=quantity_text(remaining), scheduled=scheduled,
        material_inbound_date=inbound_date.isoformat() if inbound_date else None,
        group_status=('人工完成需求' if group.manual_completed_at else '已建需求') if group else '需求未建',
        required_root_count=str(required_roots) if is_pipe and root_valid else None,
        purchased_root_count=quantity_text(purchased_roots) if is_pipe and root_valid and reliable else None,
        remaining_root_count=quantity_text(max(Decimal(required_roots)-purchased_roots, Decimal('0')))
            if is_pipe and root_valid and reliable else None, root_count_note=root_note,
        risks=coverage_risks(required=required, purchased=purchased, scheduled=scheduled, reliable=reliable,
                             changed=changed, history=history))
    _coverage_actions(row, task, group, bom, reliable, remaining)
    return row


def _combined_coverage_rows(task, group, products, boms, purchases_by_source, previous_lines, materials, schedules, evaluated_at,
                            unknown_task, policy, now):
    """一条合并物料只计算一次采购量，逐份 BOM 核对原始用量及其变更。"""
    members = {item.product_line_id_snapshot: item for item in group.bom_sources.all()}
    current = {}
    product_notes = defaultdict(list)
    for pk in members:
        product = products.get(pk)
        bom = boms.get(product.tracking_bom_id) if product else None
        if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product.quantity:
            product_notes[pk].append('最新BOM缺失、尚未确认或与任务产品数量不一致')
        if bom:
            current[pk] = {str(line.component_identity): _bom_snapshot(line, bom, materials)
                for section in bom.sections.all() if _is_purchasable_bom_section(section)
                for line in section.lines.all() if line.purchase_required}
    frozen_components = defaultdict(set)
    for source in group.lines.all():
        for item in source.source_snapshot.get('source_contributions', []):
            if item['source_snapshot'].get('purchase_required') is not False:
                frozen_components[_uuid(item['product_line_id'])].add(item['component_identity'])
    for pk in members:
        if set(current.get(pk, {})) != frozen_components[pk]:
            product_notes[pk].append('当前BOM行集合与冻结采购需求不同，需核对增补或跨版本来源')
    rows = []
    history = bool(task.archived_at or task.status in TERMINAL_TASK_STATUSES)
    for source in group.lines.all():
        snapshot = source.source_snapshot
        if snapshot.get('purchase_required') is False:
            continue
        items = snapshot.get('source_contributions', [])
        identity, notes = _identity(snapshot, materials)
        if unknown_task:
            notes.append('历史采购明细的产品归属无法核实')
        if group.compatibility_issues or source.compatibility_issues or not items:
            notes.append('冻结来源行待核对')
        if task.status == 'PAUSED' and not task.accepted_by_employee_id and not task.started_at:
            notes.append('历史暂停任务的已接单来源待核对')
        origins = {source.pk: (group.pk, identity)}
        product_names = {}
        changed = False
        for item in items:
            pk = _uuid(item['product_line_id'])
            original = item['source_snapshot']
            original_identity, original_notes = _identity(original, materials)
            previous_line_id = _uuid(item.get('previous_group_line_id'))
            if previous_line_id and pk in members:
                origins[previous_line_id] = (members[pk].previous_group_id, original_identity)
            if original.get('purchase_required') is False:
                continue
            product_names[pk] = ' '.join(filter(None, (item['product_name'], item.get('product_color'))))
            notes.extend(original_notes)
            notes.extend(product_notes[pk])
            present = current.get(pk, {}).get(item['component_identity'])
            if present:
                notes.extend(present[2])
            if product_notes[pk] or not present or _semantic(original, original_identity) != _semantic(present[0], present[1]):
                changed = True
                notes.append('当前BOM的材料、数量、单位或管材参数已改变')
        for key in snapshot.get('previous_group_line_ids', []):
            old = previous_lines.get(_uuid(key))
            if old:
                old_identity, old_notes = _identity(old.source_snapshot, materials)
                notes.extend(old_notes)
                origins[old.pk] = (old.purchase_group_id, old_identity)
            else:
                notes.append('原采购需求行待核对')
        candidates = [boms[products[pk].tracking_bom_id] for pk in product_names
                      if pk in products and products[pk].tracking_bom_id in boms]
        # 共用料按涉及产品中最早的已知需求日期检查，缺失的确认时间仍须显示待核对。
        bom = min(candidates, key=lambda obj: (obj.confirmed_at is not None, obj.confirmed_at, obj.pk), default=None)
        dates = [schedules[pk]['material_inbound_date'] for pk in product_names if not history and pk in schedules]
        purchases = [(line, expected_identity, line.purchase_order.purchase_group_id == group_id)
                     for source_id, (group_id, expected_identity) in origins.items()
                     for line in purchases_by_source[source_id]]
        row = _coverage_material_row(task, group, bom, snapshot,
            product_id=next(iter(product_names)) if len(product_names) == 1 else None,
            product_name=' / '.join(product_names.values()), source_id=source.source_bom_line_id_snapshot,
            row_key=f'{task.pk}:{group.pk}:{source.pk}', required=source.required_quantity,
            purchases=purchases, materials=materials, notes=notes, changed=changed, history=history,
            scheduled=bool(dates), inbound_date=min(dates) if dates and None not in dates else None, evaluated_at=evaluated_at)
        if policy is not None:
            _apply_coverage_timing(row, bom, now, policy)
        rows.append(row)
    for pk in members:
        if not frozen_components[pk] and current.get(pk):
            product = products[pk]
            bom = boms.get(product.tracking_bom_id)
            row = _unknown_product_row(task, product, group, bom, not history and pk in schedules,
                schedules, history, product_notes[pk], evaluated_at, changed=True)
            if policy is not None:
                _apply_coverage_timing(row, bom, now, policy)
            rows.append(row)
    return rows


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
                     if _is_purchasable_bom_section(section) for line in section.lines.all() if line.purchase_required]
    groups = list(PurchaseGroup.objects.filter(production_task_id__in=tasks, archived_at__isnull=True)
        .only('id', 'production_task_id', 'product_line_id_snapshot', 'compatibility_issues', 'manual_completed_at')
        .prefetch_related('bom_sources', Prefetch('lines', queryset=PurchaseGroupLine.objects.only('id', 'purchase_group_id',
            'source_bom_line_id_snapshot', 'product_line_id_snapshot', 'required_quantity', 'source_snapshot', 'compatibility_issues'))))
    combined_groups = [group for group in groups if not group.product_line_id_snapshot and group.bom_sources.all()]
    combined_ids = {group.pk for group in combined_groups}
    combined_products = {item.product_line_id_snapshot for group in combined_groups for item in group.bom_sources.all()}
    prior_ids = {item.previous_group_id for group in combined_groups for item in group.bom_sources.all() if item.previous_group_id}
    previous_lines = {line.pk: line for group in groups if group.pk in prior_ids for line in group.lines.all()}
    group_map = defaultdict(list)
    revised_source_ids = []
    for group in groups:
        if group.pk in combined_ids or group.pk in prior_ids:
            continue
        group_map[(group.production_task_id, group.product_line_id_snapshot)].append(group)
        if any(isinstance(row.source_snapshot, dict) and 'purchase_required' in row.source_snapshot
               for row in group.lines.all()):
            revised_source_ids.extend(row.source_bom_line_id_snapshot for row in group.lines.all())
    frozen_row_ids = {(product_id, identity): str(pk) for product_id, identity, pk in
                      BomLine.objects.filter(pk__in=revised_source_ids).values_list(
                          'section__bom__product_line_id', 'component_identity', 'pk')}
    purchase_lines = list(PurchaseOrderLine.objects.filter(purchase_order__production_task_id__in=tasks,
        purchase_order__source_type='PRODUCTION', purchase_order__archived_at__isnull=True,
        purchase_order__status__in=VALID_PURCHASE_STATUSES).select_related('purchase_order')
        .only(*LINE_IDENTITY_FIELDS, 'purchase_order__production_task_id', 'purchase_order__purchase_group_id').order_by('id'))
    purchase_map = defaultdict(list)
    purchases_by_source = defaultdict(list)
    for line in purchase_lines:
        purchase_map[(line.purchase_order.production_task_id, line.product_line_id_snapshot)].append(line)
        purchases_by_source[line.purchase_group_line_id].append(line)
    unresolved_product_tasks = {group.production_task_id for group in groups
        if group.pk not in combined_ids and group.product_line_id_snapshot not in product_ids_by_task[group.production_task_id]}
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
            if product.pk in combined_products:
                continue
            task = tasks[product.production_task_id]
            history = bool(task.archived_at or task.status in TERMINAL_TASK_STATUSES)
            scheduled = not history and product.pk in schedules
            bom = boms.get(product.tracking_bom_id)
            product_notes = []
            if task.pk in unresolved_product_tasks:
                product_notes.append('历史采购需求或采购明细的产品归属无法核实，不能当作未采购')
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
                product_notes.append('采购需求产品归属不唯一')
            if group and group.compatibility_issues:
                product_notes.append('采购需求来源存在历史待核对项')
            current = {}
            external_ids = set()
            if bom:
                for section in bom.sections.all():
                    if _is_purchasable_bom_section(section):
                        for line in section.lines.all():
                            if not line.purchase_required:
                                external_ids.add(str(line.pk))
                                continue
                            source_id = frozen_row_ids.get((product.pk, line.component_identity), str(line.pk))
                            current[source_id] = _bom_snapshot(line, bom, materials)
            source_lines = [line for line in group.lines.all()
                            if not isinstance(line.source_snapshot, dict)
                            or line.source_snapshot.get('purchase_required') is not False] if group else []
            if bom and bom.status == 'VERIFIED' and external_ids and not current and not source_lines:
                continue
            if not current:
                product_notes.append('没有可核实的采购需求行')
            known_sources = ({str(line.source_bom_line_id_snapshot) for line in group.lines.all()}
                             if group else set(current) | external_ids)
            if any(str(line.source_bom_line_id_snapshot) not in known_sources
                   for line in purchase_map.get((task.pk, product.pk), [])):
                product_notes.append('历史采购无法核实BOM需求行归属，不能当作未采购')
            if group and set(current) != {str(line.source_bom_line_id_snapshot) for line in source_lines}:
                rows.append(_unknown_product_row(task, product, group, bom, scheduled, schedules, history,
                    product_notes + ['当前BOM行集合与冻结采购需求不同，需核对增补或跨版本来源'], evaluated_at,
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
                if purchase_map.get((task.pk, None)):
                    notes.append('历史采购无法核实产品归属，不能当作未采购')
                purchases = [(line, identity, not group or (line.purchase_order.purchase_group_id == group.pk
                    and line.purchase_group_line_id == frozen_line.pk)) for line in purchase_map.get((task.pk, product.pk), [])
                    if str(line.source_bom_line_id_snapshot) == source_id]
                rows.append(_coverage_material_row(task, group, bom, snapshot,
                    product_id=product.pk, product_name=product.product_name_snapshot, source_id=source_id,
                    row_key=f'{task.pk}:{product.pk}:{source_id}', required=required, purchases=purchases,
                    materials=materials, notes=notes, changed=changed, history=history, scheduled=scheduled,
                    inbound_date=schedules[product.pk]['material_inbound_date'] if scheduled else None, evaluated_at=evaluated_at))
    if policy is not None:
        boms_by_product = {bom.product_line_id: bom for bom in boms.values()}
        for row in rows:
            bom = boms_by_product.get(_uuid(row['product_line_id']))
            _apply_coverage_timing(row, bom, now, policy)
    products_by_id = {product.pk: product for product in products}
    with localcontext() as context:
        context.prec = 64
        for group in combined_groups:
            rows.extend(_combined_coverage_rows(tasks[group.production_task_id], group, products_by_id, boms,
                purchases_by_source, previous_lines, materials, schedules, evaluated_at, group.production_task_id in unresolved_product_tasks,
                policy, now))
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
        row['actions'].append({'kind': 'view_group', 'label': '查看需求', 'path': f'/purchase-groups/{group.pk}'})
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
            row['actions'].append({'kind': 'create_group', 'label': '创建需求',
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
