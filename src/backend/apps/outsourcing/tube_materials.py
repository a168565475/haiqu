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
from apps.inventory.models import MaterialStockMovement, PublicStockBalance, PublicStockMovement, WarehouseZone
from apps.inventory.public_stock_identity import validate_public_identity
from apps.inventory.public_stock_services import debit_public_stock
from apps.inventory.stock_services import debit_material_stock
from apps.inventory.tube_outsourcing_reservations import tube_material_reserved_quantities
from apps.material_issues.public_issue_services import public_issue_quantity_context, public_line_quantities, _pool
from apps.material_issues.catalog_requirements import catalog_requirement_specs, catalog_issue_line_values, sync_catalog_requirements
from apps.material_issues.models import MaterialIssue, MaterialIssueLine, OrderMaterialRequirement
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


def _catalog_sources(product, sources, *, exclude_order_id, plan_mode, for_plan):
    """复用已确认 BOM 的新目录需求和公共库存，不创建旧原料映射。"""
    if not sources:
        return {}
    specs, blockers = catalog_requirement_specs(product.schedule.production_task_id, product.product_line_id)
    specs = {spec['line'].pk: spec for spec in specs}
    existing = {row.pk: row for row in OrderMaterialRequirement.objects.filter(pk__in=[spec['id'] for spec in specs.values()])}
    issue = MaterialIssue(production_task_id=product.schedule.production_task_id,
        product_line_id=product.product_line_id, stock_mode='PUBLIC_V2')
    facts = {}
    for line, row in sources:
        spec = specs.get(line.pk)
        if spec is None:
            row['blockers'].extend(item['detail'] for item in blockers if item.get('bom_line_id') == str(line.pk))
            row['blockers'] = row['blockers'] or ['随单材料缺少有效的保存材料、数量或单位。']
            continue
        selected, identity = spec['selected'], spec['snapshot']['public_identity']
        if identity['stock_kind'] != 'CATALOG_RAW':
            row['blockers'].append('附带料须使用已保存原料身份，不能把加工产出当原料扣减。')
            continue
        requirement = existing.get(spec['id']) or OrderMaterialRequirement(id=spec['id'],
            production_task_id=issue.production_task_id, product_line_id=issue.product_line_id,
            component_identity=line.component_identity, measurement_kind='CATALOG', line_type='RAW')
        requirement.material_catalog_id = line.material_catalog_id
        requirement.material_selection_snapshot = selected
        requirement.conversion_snapshot = spec['snapshot']
        requirement.unit = spec['unit']
        requirement.required_quantity = spec['quantity']
        requirement.source_revision_hash = spec['revision']
        issue_line = MaterialIssueLine(issue=issue, requested_quantity=1, **catalog_issue_line_values(requirement))
        attrs = selected['attributes']
        row.update(name=selected['name'], material_number='', material=attrs.get('material', ''),
            specification=issue_line.specification_snapshot, color=attrs.get('color', ''), unit=selected['unit_name'],
            material_catalog_id=selected['catalog_id'], material_selection_snapshot=selected)
        facts[str(line.pk)] = dict(bom_line=line, raw=None, row=row, unit=spec['unit'],
            issue_line=issue_line, requirement=requirement, identity=identity)
    stock = public_issue_quantity_context(issue, lines=[fact['issue_line'] for fact in facts.values()],
        exclude_tube_order_id=exclude_order_id)
    for fact in facts.values():
        row, issue_line = fact['row'], fact['issue_line']
        pool = _pool(issue_line)
        values = public_line_quantities(issue_line, context=stock)
        row.update(required_quantity=_quantity_text(values['required_quantity']),
            order_remaining=_quantity_text(values['order_remaining']),
            available_stock=_quantity_text(max(stock['stock'][pool] - stock['pending_stock'][pool], ZERO)),
            max_quantity=_quantity_text(values['max_issue_quantity']))
        row['zones'] = [{'zone_id': str(balance.zone_id), 'zone_name': balance.zone.zone_name,
            'warehouse_id': str(balance.zone.warehouse_id), 'warehouse_name': balance.zone.warehouse.warehouse_name,
            'available_quantity': _quantity_text(max(balance.quantity - stock['tube_reserved_by_zone'].get(
                (pool, str(balance.zone_id)), ZERO), ZERO))} for balance in stock['balances'][pool]]
        if plan_mode:
            row['max_quantity'] = row['required_quantity'] if for_plan else row['available_stock']
        if for_plan:
            available = {value['zone_id']: value for value in row['zones']}
            row['zones'] = [available.get(str(zone.pk), {'zone_id': str(zone.pk), 'zone_name': zone.zone_name,
                'warehouse_id': str(zone.warehouse_id), 'warehouse_name': zone.warehouse.warehouse_name,
                'available_quantity': '0'}) for zone in WarehouseZone.objects.filter(status='ACTIVE',
                    warehouse__status='ACTIVE', warehouse__warehouse_type='MATERIAL').select_related('warehouse')]
    return facts


def _context(product, *, exclude_order_id=None, source_kind='RAW_PIPE', plan_mode=False, for_plan=False):
    cutting = source_kind in CUTTING_SOURCES
    section_title = '辅料类' if cutting else '五金件'
    bom = Bom.objects.filter(product_line_id=product.product_line_id, archived_at__isnull=True).order_by(
        '-version_number', '-updated_at', '-pk').first()
    bom_lines = [line for line in BomLine.objects.filter(section__bom=bom).select_related(
        'section__bom').order_by('pk') if line.section.title.strip() == section_title] if bom else []
    rows, items, raws, sources, catalog_sources = [], [], {}, {}, []
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
        if line.material_catalog_id:
            catalog_sources.append((line, row))
            continue
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
            if plan_mode:
                row['max_quantity'] = row['required_quantity'] if for_plan else row['available_stock']
            if for_plan:
                available_zones = {value['zone_id']: value for value in row['zones']}
                row['zones'] = [available_zones.get(str(zone.pk), {
                    'zone_id': str(zone.pk), 'zone_name': zone.zone_name,
                    'warehouse_id': str(zone.warehouse_id), 'warehouse_name': zone.warehouse.warehouse_name,
                    'available_quantity': '0'}) for zone in WarehouseZone.objects.filter(
                        status='ACTIVE', warehouse__status='ACTIVE', warehouse__warehouse_type='MATERIAL').select_related('warehouse')]
            facts[str(item.pk)] = {**source, 'issue_line': issue_line, 'requirement': issue_line.requirement,
                                  'unit': raw.unit, 'identity': None}
    facts.update(_catalog_sources(product, catalog_sources, exclude_order_id=exclude_order_id,
        plan_mode=plan_mode, for_plan=for_plan))
    revision = _json_hash({'bom_id': str(bom.pk) if bom else None,
        'bom_version': bom.version_number if bom else None, 'rows': rows,
        'identities': {key: {'raw_id': str(value['raw'].pk) if value['raw'] else None,
            'public_identity': value['identity'], 'unit_id': str(value['unit'].pk),
            'requirement_id': str(value['requirement'].pk)} for key, value in facts.items()}})
    return {'material_rows': rows, 'material_source_revision': revision}, facts


def tube_material_context(product, *, source_kind='RAW_PIPE', plan_mode=False, for_plan=False):
    return _context(product, source_kind=source_kind, plan_mode=plan_mode, for_plan=for_plan)[0]


def lock_material_sources(product, entered, *, source_kind='RAW_PIPE'):
    """先同步既有普通原料额度，余额锁由来源准备服务与随单材料一次性取得。"""
    if not entered:
        return []
    lock_source_product(product.product_line_id, source_kind)
    sync_order_requirements(product.schedule.production_task_id)
    selected = {str(row['bom_line_id']) for row in entered}
    specs, _ = catalog_requirement_specs(product.schedule.production_task_id, product.product_line_id)
    catalog_ids = [spec['id'] for spec in specs if str(spec['line'].pk) in selected]
    if catalog_ids:
        sync_catalog_requirements(MaterialIssue(production_task_id=product.schedule.production_task_id,
            product_line_id=product.product_line_id, stock_mode='PUBLIC_V2'), catalog_ids)
    _, facts = _context(product, source_kind=source_kind)
    if selected - facts.keys():
        raise ValidationError({'materials': '所选随单材料不属于当前已确认BOM，或原料、单位、订单需求未就绪。'})
    return [facts[key]['issue_line'] for key in sorted(selected)]


def prepare_materials(product, entered, *, expected_revision=None, exclude_order_id=None, frozen=None, source_kind='RAW_PIPE', plan_mode=False):
    """调用方已锁齐加工部位与随单材料库存；整单合计校验订单额度、物料池及库区。"""
    if not entered:
        return []
    context, facts = _context(product, exclude_order_id=exclude_order_id, source_kind=source_kind, plan_mode=plan_mode)
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
        raw, requirement, unit = source['raw'], source['requirement'], source['unit']
        if frozen is not None:
            saved = frozen[str(row['material_id'])]
            if (saved.factory_id != row['factory_id'] or saved.raw_material_id != (raw.pk if raw else None)
                    or saved.material_catalog_id != requirement.material_catalog_id
                    or (saved.material_catalog_id and (saved.material_selection_snapshot != requirement.material_selection_snapshot
                        or saved.snapshot.get('public_identity') != source['identity']))
                    or saved.unit_id != unit.pk or saved.requirement_id != requirement.pk
                    or any(saved.snapshot.get(key) != source['row'][key]
                           for key in ('material_number', 'name', 'specification', 'material', 'color', 'unit'))):
                raise Conflict('随单材料实物或单位与原单冻结依据不一致，请取消后重新创建。')
        pool = _pool(source['issue_line'])
        by_requirement[requirement.pk] += row['quantity']
        by_pool[pool] += row['quantity']
        by_zone[(*pool, str(zone.pk))] += row['quantity']
        prepared.append({**source, 'entered': row, 'zone': zone})
    for source in prepared:
        requirement, row = source['requirement'], source['row']
        pool = _pool(source['issue_line'])
        if not plan_mode and by_requirement[requirement.pk] > Decimal(row['order_remaining']):
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
        if value['identity']:
            snapshot.update(public_identity=value['identity'],
                material_selection_snapshot=value['requirement'].material_selection_snapshot)
        materials.append(TubeOutsourcingMaterial(order=order, factory=factory, bom_line=value['bom_line'],
            requirement=value['requirement'], raw_material=value['raw'], unit=value['unit'],
            material_catalog_id=value['requirement'].material_catalog_id,
            material_selection_snapshot=value['requirement'].material_selection_snapshot if value['identity'] else {},
            zone=zone, quantity=entered['quantity'], snapshot=snapshot))
    TubeOutsourcingMaterial.objects.bulk_create(materials)
    return materials


def material_data(material):
    snapshot = material.snapshot
    return {'id': str(material.pk), 'bom_line_id': str(material.bom_line_id),
        'component_identity': str(material.order_line.component_identity) if material.order_line_id else None,
        'order_line_id': str(material.order_line_id) if material.order_line_id else None,
        'factory_id': str(material.factory_id), 'quantity': str(material.quantity), 'zone_id': str(material.zone_id),
        'material_catalog_id': str(material.material_catalog_id) if material.material_catalog_id else None,
        'material_selection_snapshot': material.material_selection_snapshot,
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
        kwargs = dict(quantity=material.quantity, source_type=MOVEMENT_SOURCE, source_id=order.pk, source_line_id=material.pk,
            actor_employee=request.employee, production_task=order.schedule_product.schedule.production_task,
            snapshot={**material.snapshot, 'stock_mode': 'PUBLIC_V2',
                'order_id': str(order.pk), 'order_line_id': str(material.order_line_id) if material.order_line_id else None,
                'factory_id': str(material.factory_id), 'bom_line_id': str(material.bom_line_id)})
        if material.material_catalog_id:
            identity = validate_public_identity(material.snapshot.get('public_identity'))
            balance = PublicStockBalance.objects.filter(stock_kind=identity['stock_kind'],
                identity_key=identity['identity_key'], unit_id=identity['unit_id'], zone_id=material.zone_id,
                quality='AVAILABLE').first()
            if balance is None:
                raise Conflict('原单附带材料来源库区公共库存已不足，请刷新后重试。')
            movement = debit_public_stock(balance_id=balance.pk, product_line=order.product_line,
                bom_line=material.bom_line, **kwargs)
        else:
            movement = debit_material_stock(raw_material=value['raw'], unit=value['unit'], zone=material.zone, **kwargs)
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
    movements = [movement for model in (MaterialStockMovement, PublicStockMovement) for movement in
        model.objects.filter(source_type=MOVEMENT_SOURCE, source_id=order.pk, direction='OUT').select_related('balance')]
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
        if material.material_catalog_id:
            try:
                identity = validate_public_identity(material.snapshot.get('public_identity'))
            except ValidationError:
                return ['附带材料缺少有效的冻结公共库存身份。']
            if (not isinstance(movement, PublicStockMovement)
                    or identity['identity_snapshot']['material_selection_snapshot'] != material.material_selection_snapshot
                    or material.material_selection_snapshot.get('catalog_id') != str(material.material_catalog_id)
                    or movement.balance.stock_kind != identity['stock_kind']
                    or movement.balance.identity_key != identity['identity_key']
                    or movement.snapshot.get('public_identity') != identity):
                return ['附带材料扣库流水与冻结目录材料不一致。']
    return []
