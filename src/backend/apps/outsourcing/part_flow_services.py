"""已锁定部位总单的分次实发；多裁片投入与部位回货分别记录。"""
from decimal import Decimal
from collections import defaultdict

from rest_framework.exceptions import ValidationError

from apps.core.api.exceptions import Conflict
from apps.core.audit import write_audit_log
from apps.core.numbering import next_business_number
from apps.inventory.models import PublicStockBalance
from apps.inventory.public_stock_services import debit_public_stock

from .models import OutsourcingFactory, TubeOutsourcingOrder, TubeOutsourcingLine, TubeOutsourcingInput, TubeOutsourcingAction
from .part_flow_sources import part_source_context, input_dispatched
from .component_source_snapshots import frozen_component_source_materials
from .plan_selectors import plan_quantities
from .tube_selectors import source_product, source_zone, source_factories, DISPATCH_PERMISSION
from .tube_services import _json


def dispatch_parts(*, order, data, request, payload_hash):
    sewing = bool(order.source_snapshot.get('sewing_inputs'))
    entered = data.get('inputs' if sewing else 'lines', [])
    if not entered or data.get('lines' if sewing else 'inputs'):
        raise ValidationError({'inputs': '车缝发出裁片；丝印、刺绣发出原部位。'})
    product, craft = source_product(request, order.schedule_product_id, DISPATCH_PERMISSION,
        source_kind=data['source_kind'], craft_id=order.craft_id)
    zone = source_zone(data['source_kind'], data.get('zone_id'))
    targets = {str(line.component_identity): line for line in order.lines.select_for_update(of=('self',)).order_by('pk')}
    frozen = {piece['component_identity']: (line, piece) for line in targets.values()
              for piece in line.snapshot.get('pieces', [])} if sewing else {key: (line, {}) for key, line in targets.items()}
    if any(str(value['component_identity']) not in frozen for value in entered):
        raise ValidationError({'inputs': '投入部件不属于本总单保存的部位组成。'})
    from .tube_materials import lock_material_sources, prepare_materials, save_materials, dispatch_materials
    from apps.material_issues.models import MaterialIssue, MaterialIssueLine
    from apps.material_issues.public_issue_services import _lock_public_issue_stock
    material_inputs = data.get('materials', [])
    assignment = order.source_snapshot.get('sewing_part_assignments')
    if assignment:
        if any(str(row['factory_id']) == assignment['internal_factory_id'] for row in material_inputs):
            raise ValidationError({'materials': '附带外发辅料应选择外厂，本厂用料请在车间领料。'})
    stock_lines = lock_material_sources(product, material_inputs, source_kind=data['source_kind'])
    issue = MaterialIssue(production_task_id=product.schedule.production_task_id,
        product_line_id=order.product_line_id, stock_mode='PUBLIC_V2')
    if zone:
        for value in entered:
            target, piece = frozen[str(value['component_identity'])]
            identity = piece['input_identity'] if sewing else target.input_identity
            stock_lines.append(MaterialIssueLine(id=piece['bom_line_id'] if sewing else target.bom_line_id,
                issue=issue, line_type='SEMI', unit_id=identity['unit_id'], requested_quantity=1,
                conversion_snapshot={'kind': 'PUBLIC_SEMI', 'public_identity': identity}))
    if stock_lines:
        _lock_public_issue_stock(issue, stock_lines)
    context = part_source_context(schedule_product=product, source_kind=data['source_kind'], zone=zone, craft=craft)
    rows = {row['component_identity']: row for row in context['inputs' if sewing else 'rows']}
    current_parts = {row['component_identity']: row for row in context['rows']}
    sent = input_dispatched(order) if sewing else {str(line.component_identity): int(values['dispatched_quantity'])
        for line in targets.values() for values in [plan_quantities([order])[str(order.pk)]['lines'][str(line.pk)]]}
    factory_ids = source_factories(request, craft, DISPATCH_PERMISSION).values('pk')
    factories = {value.pk: value for value in OutsourcingFactory.objects.filter(pk__in=factory_ids).select_for_update(of=('self',))}
    pending, pool_quantities, pool_available = [], defaultdict(int), {}
    for value in entered:
        key = str(value['component_identity'])
        if key not in frozen or key not in rows:
            raise ValidationError({'inputs': '投入部件不属于本总单保存的部位组成。'})
        target, piece = frozen[key]
        row = rows[key]
        current_part = current_parts.get(str(target.component_identity))
        if (not current_part or current_part['blockers'] or
                current_part['snapshot'].get('public_output_identity') != target.snapshot['public_output_identity']):
            raise Conflict('当前 BOM 的部位组成与总单保存身份不一致。')
        if row['blockers'] or target.factory_id not in factories:
            raise ValidationError({'inputs': '部件身份或总单加工厂已失效，请刷新核对。'})
        if not sewing and value.get('factory_id') != target.factory_id:
            raise ValidationError({'lines': '本次部位发货须使用总单保存的加工厂。'})
        identity = piece.get('input_identity') if sewing else target.input_identity
        if identity != row['input_identity']:
            raise Conflict('当前 BOM 的投入实物与总单保存身份不一致。')
        if not sewing and target.snapshot['public_output_identity'] != row['snapshot']['public_output_identity']:
            raise Conflict('当前 BOM 的产出部位与总单保存身份不一致。')
        ceiling = target.quantity * piece['pieces_per_part'] if sewing else target.quantity
        quantity = value['quantity']
        if quantity > max(ceiling-sent.get(key, 0), 0):
            raise ValidationError({'inputs': f'“{row["part_name"]}”累计实发不能超过总单目标对应的{ceiling}{row["unit"]}。'})
        if quantity > Decimal(row['max_quantity']):
            raise Conflict(f'“{row["part_name"]}”的来源可用数量不足，请刷新。')
        if zone:
            pool = (identity['stock_kind'], identity['identity_key'], identity['unit_id'], str(zone.pk))
            pool_quantities[pool] += quantity
            pool_available[pool] = min(pool_available.get(pool, Decimal(row['max_quantity'])), Decimal(row['max_quantity']))
        pending.append((target, row, quantity, identity))
    if any(quantity > pool_available[pool] for pool, quantity in pool_quantities.items()):
        raise Conflict('同一实物的多行裁片或部位合计超过可用库存，已扣除待审领料和其他待发预留。')
    if any(value['factory_id'] not in factories for value in material_inputs):
        raise ValidationError({'materials': '附带辅料加工厂无效或未授权。'})
    prepared = prepare_materials(product, material_inputs, expected_revision=data.get('material_source_revision'),
        source_kind=data['source_kind'], plan_mode=True)
    batch = TubeOutsourcingOrder.objects.create(plan=order, order_number=next_business_number('OUTSOURCING_ORDER'),
        schedule_product=product, product_line=order.product_line, bom=order.bom, craft=craft,
        source_kind=data['source_kind'], zone=zone, planned_dispatch_date=data['actual_dispatch_date'],
        expected_return_date=max(order.expected_return_date, data['actual_dispatch_date']), status='PROCESSING',
        remark=data.get('remark', ''), client_request_id=data['client_request_id'], request_payload_hash=payload_hash,
        source_revision_hash=context['source_revision'], source_snapshot={'part_flow': True, 'sewing_inputs': sewing,
            'fees_deferred': bool(order.source_snapshot.get('fees_deferred')),
            'billing_basis': order.source_snapshot.get('billing_basis'), 'plan_dispatch_payload_hash': payload_hash},
        created_by_employee=request.employee, updated_by_employee=request.employee)
    movements = []
    for target, row, quantity, identity in pending:
        snapshot = {**(row if sewing else target.snapshot), 'part_name': row['part_name'], 'unit': row['unit'],
            'factory_name': factories[target.factory_id].name, 'part_flow': True}
        snapshot['component_source_materials'] = frozen_component_source_materials(
            frozen[row['component_identity']][1] if sewing else target.snapshot, identity)
        snapshot.pop('input_identity', None)
        stock_quantity = quantity if zone else None
        fields = dict(order=batch, bom_line_id=row['bom_line_id'], component_identity=row['component_identity'],
            quantity=quantity, factory=target.factory, stock_quantity=stock_quantity,
            input_identity=_json(identity), snapshot=_json(snapshot))
        line = (TubeOutsourcingInput.objects.create(parent_line=target, source_kind=data['source_kind'], **fields)
                if sewing else TubeOutsourcingLine.objects.create(unit_price=None, **fields))
        if zone:
            balance = PublicStockBalance.objects.filter(stock_kind=identity['stock_kind'], identity_key=identity['identity_key'],
                unit_id=identity['unit_id'], zone=zone, quality='AVAILABLE').first()
            if balance is None:
                raise Conflict('所选来源库区没有该实物库存。')
            movement = debit_public_stock(balance_id=balance.pk, quantity=quantity,
                source_type='TUBE_OUTSOURCING_DISPATCH', source_id=batch.pk, source_line_id=line.pk,
                actor_employee=request.employee, production_task=product.schedule.production_task_id,
                product_line=order.product_line_id, bom_line=line.bom_line_id,
                snapshot=_json({'public_identity': identity, 'order_number': batch.order_number,
                    'source_kind': data['source_kind'], 'quantity': quantity}))
            movements.append({'line_id': str(line.pk), 'movement_id': str(movement.pk)})
    materials = save_materials(batch, prepared, factories)
    planned_materials = {row['bom_line_id']: row for row in order.source_snapshot.get('planned_materials', [])}
    for material in materials:
        planned = planned_materials.get(str(material.bom_line_id))
        if planned and planned.get('material_catalog_id') and (
                str(material.material_catalog_id) != planned['material_catalog_id']
                or material.material_selection_snapshot != planned['material_selection_snapshot']):
            raise Conflict('实际发出辅料与总单保存的材料身份不一致。')
    material_movements = dispatch_materials(batch, materials, prepared, request)
    action = TubeOutsourcingAction.objects.create(order=batch, kind='DISPATCH', client_request_id=data['client_request_id'],
        request_payload_hash=payload_hash, actual_dispatch_date=data['actual_dispatch_date'],
        actor_employee=request.employee, remark=data.get('remark', ''),
        snapshot={'quantity': sum(quantity for _, _, quantity, _ in pending), 'source_revision': context['source_revision'],
            'movements': movements, 'material_movements': material_movements})
    from .plan_services import _update_plan
    _update_plan(order, request)
    write_audit_log(object_type='TUBE_OUTSOURCING_ORDER', object_id=batch.pk, action='DISPATCH_CONFIRMED',
        actor_employee=request.employee, after_data={'plan_id': str(order.pk), 'order_number': batch.order_number,
            'status': batch.status, 'source_kind': batch.source_kind, 'action_id': str(action.pk),
            'actual_dispatch_date': str(data['actual_dispatch_date']), 'inputs': sewing,
            'movements': movements, 'material_movements': material_movements,
            'quantities': [{'component_identity': row['component_identity'], 'quantity': quantity,
                'unit': row['unit']} for _, row, quantity, _ in pending]},
        context_type='PRODUCTION_SCHEDULE', context_id=product.schedule_id, request=request)
    return order, True
