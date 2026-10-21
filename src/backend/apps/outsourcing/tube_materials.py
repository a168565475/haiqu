"""同单附带五金或辅料：复用原料身份、订单额度和库存记账，不创建加工产出。"""
from collections import defaultdict
from decimal import Decimal
from types import SimpleNamespace

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.boms.material_attributes import bom_attribute_fields
from apps.boms.models import Bom, BomLine
from apps.core.api.concurrency import PreconditionFailed
from apps.core.api.exceptions import Conflict
from apps.inventory.models import MaterialStockMovement, WarehouseZone
from apps.inventory.stock_services import debit_material_stock
from apps.inventory.tube_outsourcing_reservations import tube_material_reserved_quantities
from apps.material_issues.public_issue_services import public_issue_quantity_context, public_line_quantities
from apps.material_issues.requirements import sync_order_requirements
from apps.products.material_identity import resolve_bom_line_raw_material

from .models import TubeOutsourcingMaterial
from .public_stock_services import _lines, _requirements, _stock_rows
from .services import _json_hash
from .tube_kinds import CUTTING_SOURCES, lock_source_product


MOVEMENT_SOURCE = 'TUBE_OUTSOURCING_MATERIAL_DISPATCH'
ZERO = Decimal(0)


def _quantity_text(value):
    return format(Decimal(value).normalize(), 'f')


def _context(product, *, exclude_order_id=None, source_kind='RAW_PIPE'):
    cutting = source_kind in CUTTING_SOURCES
    section_title = '辅料类' if cutting else '五金件'
    bom = Bom.objects.filter(product_line_id=product.product_line_id, archived_at__isnull=True).order_by(
        '-version_number', '-updated_at', '-pk').first()
    bom_lines = [line for line in BomLine.objects.filter(section__bom=bom).select_related(
        'section__bom').order_by('pk') if line.section.title.strip() == section_title] if bom else []
    rows, items, raws, sources = [], [], {}, {}
    allocation = SimpleNamespace(processing_item=SimpleNamespace(order_product=SimpleNamespace(schedule_product=product)))
    for line in bom_lines:
        fields = {item['key']: item['value'] for item in bom_attribute_fields(line)}
        row = {'bom_line_id': str(line.pk), 'material_number': fields.get('hardware_material_number') or line.source_serial,
            'name': line.part_name or line.material or line.raw_material,
            'specification': line.specification, 'material': fields.get('material') or line.material,
            'color': fields.get('accessory_color' if cutting else 'hardware_color') or '', 'unit': line.unit,
            'required_quantity': '0', 'order_remaining': '0', 'available_stock': '0', 'max_quantity': '0',
            'blockers': [], 'zones': []}
        rows.append(row)
        raw, _ = resolve_bom_line_raw_material(line)
        if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product.product_line.quantity:
            row['blockers'].append('请先确认当前产品数量一致的最新BOM。')
        elif raw is None:
            row['blockers'].append('随单材料缺少有效的库存原料关联。')
        elif (raw.archived_at or raw.item_type != 'MATERIAL' or raw.category.status != 'ACTIVE'
                or raw.category.archived_at or raw.unit.status != 'ACTIVE' or raw.unit.archived_at):
            row['blockers'].append('随单材料原料、品类或库存单位已停用。')
        elif line.unit.strip() not in {raw.unit.unit_name, raw.unit.unit_code}:
            row['blockers'].append('随单材料须按其实际库存单位发料。')
        if row['blockers']:
            continue
        row['unit'] = raw.unit.unit_name
        row['material_number'] = row['material_number'] or raw.material_number
        raws[str(raw.pk)] = raw
        items.append(SimpleNamespace(pk=line.pk, bom_material_line_id=line.pk, allocation=allocation,
            conversion_snapshot={'schema_version': 2, 'kind': 'OTHER', 'raw_material_id': str(raw.pk)},
            planned_issue_quantity=ZERO))
        sources[line.pk] = {'bom_line': line, 'raw': raw, 'row': row}
    order = SimpleNamespace(schedule=product.schedule)
    requirements = _requirements(order, items) if items else {}
    ready_items = []
    for item in items:
        if item.bom_material_line_id not in requirements:
            sources[item.pk]['row']['blockers'].append('随单材料订单需求或库存单位尚未就绪。')
        else:
            ready_items.append(item)
    facts = {}
    if ready_items:
        issue, issue_lines = _lines(order, ready_items, requirements, raws)
        context = public_issue_quantity_context(issue, lines=list(issue_lines.values()), exclude_tube_order_id=exclude_order_id)
        balances = _stock_rows(context, issue_lines.values())
        _, reserved = tube_material_reserved_quantities(raw_material_ids=raws, exclude_order_id=exclude_order_id)
        for item in ready_items:
            source, issue_line = sources[item.pk], issue_lines[item.pk]
            row, raw = source['row'], source['raw']
            values = public_line_quantities(issue_line, context=context)
            pool = ('OTHER', str(raw.pk), str(raw.unit_id))
            row.update(required_quantity=_quantity_text(values['required_quantity']),
                order_remaining=_quantity_text(values['order_remaining']),
                available_stock=_quantity_text(max(context['stock'][pool] - context['pending_stock'][pool], ZERO)),
                max_quantity=_quantity_text(values['max_issue_quantity']))
            row['zones'] = [{'zone_id': str(balance.zone_id), 'zone_name': balance.zone.zone_name,
                'warehouse_id': str(balance.zone.warehouse_id), 'warehouse_name': balance.zone.warehouse.warehouse_name,
                'available_quantity': _quantity_text(max(balance.quantity - reserved.get(
                    (str(raw.pk), str(raw.unit_id), str(balance.zone_id)), ZERO), ZERO))}
                for balance in balances[pool]]
            facts[str(item.pk)] = {**source, 'issue_line': issue_line, 'requirement': issue_line.requirement}
    revision = _json_hash({'bom_id': str(bom.pk) if bom else None,
        'bom_version': bom.version_number if bom else None, 'rows': rows,
        'identities': {key: {'raw_id': str(value['raw'].pk), 'unit_id': str(value['raw'].unit_id),
            'requirement_id': str(value['requirement'].pk)} for key, value in facts.items()}})
    return {'material_rows': rows, 'material_source_revision': revision}, facts


def tube_material_context(product, *, source_kind='RAW_PIPE'):
    return _context(product, source_kind=source_kind)[0]


def lock_material_sources(product, entered, *, source_kind='RAW_PIPE'):
    """先同步既有普通原料额度，余额锁由来源准备服务与随单材料一次性取得。"""
    if not entered:
        return []
    lock_source_product(product.product_line_id, source_kind)
    sync_order_requirements(product.schedule.production_task_id)
    _, facts = _context(product, source_kind=source_kind)
    selected = {str(row['bom_line_id']) for row in entered}
    if selected - facts.keys():
        raise ValidationError({'materials': '所选随单材料不属于当前已确认BOM，或原料、单位、订单需求未就绪。'})
    return [facts[key]['issue_line'] for key in sorted(selected)]


def prepare_materials(product, entered, *, expected_revision=None, exclude_order_id=None, frozen=None, source_kind='RAW_PIPE'):
    """调用方已锁齐加工部位与随单材料库存；整单合计校验订单额度、物料池及库区。"""
    if not entered:
        return []
    context, facts = _context(product, exclude_order_id=exclude_order_id, source_kind=source_kind)
    if frozen is None and expected_revision != context['material_source_revision']:
        raise PreconditionFailed('随单材料BOM、库存或预留已变化，请刷新后重新确认。')
    by_requirement, by_pool, by_zone = defaultdict(Decimal), defaultdict(Decimal), defaultdict(Decimal)
    prepared = []
    for row in entered:
        source = facts.get(str(row['bom_line_id']))
        if source is None:
            raise Conflict('原单附带材料已不属于当前有效BOM或库存原料，请取消后重新创建。')
        zone = get_object_or_404(WarehouseZone.objects.select_related('warehouse'), pk=row['zone_id'])
        if zone.status != 'ACTIVE' or zone.warehouse.status != 'ACTIVE' or zone.warehouse.warehouse_type != 'MATERIAL':
            raise ValidationError({'materials': '随单材料来源库区必须属于有效材料仓。'})
        raw, requirement = source['raw'], source['requirement']
        if frozen is not None:
            saved = frozen[str(row['material_id'])]
            if (saved.factory_id != row['factory_id'] or saved.raw_material_id != raw.pk
                    or saved.unit_id != raw.unit_id or saved.requirement_id != requirement.pk
                    or any(saved.snapshot.get(key) != source['row'][key]
                           for key in ('material_number', 'name', 'specification', 'material', 'color', 'unit'))):
                raise Conflict('随单材料实物或单位与原单冻结依据不一致，请取消后重新创建。')
        pool = (str(raw.pk), str(raw.unit_id))
        by_requirement[requirement.pk] += row['quantity']
        by_pool[pool] += row['quantity']
        by_zone[(*pool, str(zone.pk))] += row['quantity']
        prepared.append({**source, 'entered': row, 'zone': zone})
    for source in prepared:
        raw, requirement, row = source['raw'], source['requirement'], source['row']
        pool = (str(raw.pk), str(raw.unit_id))
        if by_requirement[requirement.pk] > Decimal(row['order_remaining']):
            raise Conflict('附带材料合计超过订单剩余额度，已扣除厂内领料、已外发和其他待发预留。')
        if by_pool[pool] > Decimal(row['available_stock']):
            raise Conflict('附带材料合计超过可用库存，已扣除待审领料和其他待发预留。')
        zones = {item['zone_id']: Decimal(item['available_quantity']) for item in row['zones']}
        zone_id = str(source['zone'].pk)
        if by_zone[(*pool, zone_id)] > zones.get(zone_id, ZERO):
            raise Conflict('所选随单材料来源库区可用库存不足。')
    return prepared


def save_materials(order, prepared, factories):
    materials = []
    for value in prepared:
        entered, row, zone = value['entered'], value['row'], value['zone']
        factory = factories[entered['factory_id']]
        snapshot = {key: row[key] for key in ('material_number', 'name', 'specification', 'material', 'color', 'unit')}
        snapshot.update(zone_name=zone.zone_name, warehouse_id=str(zone.warehouse_id),
            warehouse_name=zone.warehouse.warehouse_name, factory_name=factory.name)
        materials.append(TubeOutsourcingMaterial(order=order, factory=factory, bom_line=value['bom_line'],
            requirement=value['requirement'], raw_material=value['raw'], unit=value['raw'].unit,
            zone=zone, quantity=entered['quantity'], snapshot=snapshot))
    TubeOutsourcingMaterial.objects.bulk_create(materials)
    return materials


def material_data(material):
    snapshot = material.snapshot
    return {'id': str(material.pk), 'bom_line_id': str(material.bom_line_id),
        'component_identity': str(material.order_line.component_identity) if material.order_line_id else None,
        'order_line_id': str(material.order_line_id) if material.order_line_id else None,
        'factory_id': str(material.factory_id), 'quantity': str(material.quantity), 'zone_id': str(material.zone_id),
        **{key: snapshot.get(key, '') for key in ('part_name', 'factory_name', 'unit', 'material_number',
            'name', 'specification', 'material', 'color', 'zone_name', 'warehouse_id', 'warehouse_name')}}


def frozen_material_inputs(materials):
    return [{'material_id': value.pk, 'bom_line_id': value.bom_line_id, 'factory_id': value.factory_id,
        'quantity': value.quantity, 'zone_id': value.zone_id} for value in materials]


def dispatch_materials(order, materials, prepared, request):
    facts = {str(value['bom_line'].pk): value for value in prepared}
    movements, by_requirement = [], defaultdict(Decimal)
    for material in materials:
        value = facts[str(material.bom_line_id)]
        movement = debit_material_stock(raw_material=value['raw'], unit=value['raw'].unit,
            quantity=material.quantity, source_type=MOVEMENT_SOURCE, source_id=order.pk, source_line_id=material.pk,
            actor_employee=request.employee, production_task=order.schedule_product.schedule.production_task,
            zone=material.zone, snapshot={**material.snapshot, 'stock_mode': 'PUBLIC_V2',
                'order_id': str(order.pk), 'order_line_id': str(material.order_line_id) if material.order_line_id else None,
                'factory_id': str(material.factory_id), 'bom_line_id': str(material.bom_line_id)})
        movements.append({'material_id': str(material.pk), 'movement_id': str(movement.pk), 'quantity': str(material.quantity)})
        by_requirement[material.requirement_id] += material.quantity
    requirements = {value['requirement'].pk: value['requirement'] for value in prepared}
    for key, amount in by_requirement.items():
        requirement = requirements[key]
        requirement.outsourcing_issued_quantity += amount
        requirement.save(update_fields=['outsourcing_issued_quantity', 'updated_at'])
    return movements


def material_dispatch_blockers(order, dispatch):
    materials = list(order.materials.all())
    saved_rows = dispatch.snapshot.get('material_movements', [])
    movements = list(MaterialStockMovement.objects.filter(source_type=MOVEMENT_SOURCE,
        source_id=order.pk, direction='OUT').select_related('balance'))
    if not materials and not saved_rows and not movements:
        return []
    if not isinstance(saved_rows, list) or any(not isinstance(row, dict) for row in saved_rows):
        return ['附带材料缺少有效的实际发出凭证。']
    saved = {row.get('material_id'): row.get('movement_id') for row in saved_rows}
    actual = {row.source_line_id: row for row in movements}
    if len(saved_rows) != len(materials) or len(saved) != len(materials) or len(actual) != len(materials) or len(movements) != len(materials):
        return ['附带材料扣库流水与原单明细数量不一致。']
    for material in materials:
        movement = actual.get(material.pk)
        if (movement is None or saved.get(str(material.pk)) != str(movement.pk)
                or movement.quantity != material.quantity or movement.balance.zone_id != material.zone_id
                or movement.balance.raw_material_id != material.raw_material_id or movement.balance.unit_id != material.unit_id):
            return ['附带材料扣库流水与冻结原料、数量或库区不一致。']
    return []
