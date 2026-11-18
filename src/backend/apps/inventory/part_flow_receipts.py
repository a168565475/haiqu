"""新 BOM 裁片入库与车缝部位入库，复用原单确认及公共记账流程。"""
from dataclasses import asdict

from django.shortcuts import get_object_or_404
from rest_framework.exceptions import ValidationError

from apps.boms.models import Bom, BomLine
from apps.material_issues.processing_selectors import digest
from apps.production_scheduling.models import ProductionScheduleProduct
from apps.reference_data.models import ProductionUnit
from apps.workshop_config.models import Craft
from .internal_receipt_quantities import ComponentDemand, ReceivedOutput, calculate_receipt
from .models import InternalSemiFinishedReceiptLine
from .part_flow_quantities import component_required_quantity, direct_output_usage
from .public_stock_identity import build_semi_finished_identity
from .public_stock_mode import public_flow_enabled
from .receipt_permissions import receipt_plans_for_category


def component_stock_craft(stage):
    query = (dict(craft_type='INTERNAL', plan_category='CUTTING') if stage == 'CUTTING'
             else dict(craft_type='EXTERNAL', outsourcing_code=stage))
    craft = Craft.objects.filter(status='ACTIVE', **query).order_by('pk').first()
    if craft is None:
        raise ValidationError({'detail': f'缺少有效的{stage}完成工艺。'})
    return craft


def uses_part_flow_receipt(schedule_product_id, category):
    if category == 'CUTTING':
        return True
    if category != 'SEWING':
        return False
    product_id = ProductionScheduleProduct.objects.filter(pk=schedule_product_id).values_list('product_line_id', flat=True).first()
    bom = Bom.objects.filter(product_line_id=product_id, archived_at__isnull=True).order_by('-version_number', '-id').first()
    return bool(bom and BomLine.objects.filter(section__bom=bom, component_kind='SEWN_PART').exists())


def load_part_flow_context(request, schedule_product_id, category, *, lock=False, exclude_receipt_id=None, confirmation=False):
    from .internal_receipt_services import require_operator, _key, _receipt_frozen_identity
    require_operator(request)
    if not public_flow_enabled():
        raise ValidationError({'detail': '公共库存流程尚未启用。'})
    plan = get_object_or_404(receipt_plans_for_category(request, category, confirmation=confirmation), pk=schedule_product_id)
    if lock:
        from .tube_processing_services import lock_tube_product_scope
        lock_tube_product_scope(plan.product_line_id)
        plan = get_object_or_404(receipt_plans_for_category(request, category, confirmation=confirmation), pk=schedule_product_id)
    task, product = plan.schedule.production_task, plan.product_line
    if task.status != 'IN_PRODUCTION':
        raise ValidationError({'detail': '生产订单必须处于生产中。'})
    query = Bom.objects.filter(product_line=product, archived_at__isnull=True).order_by('-version_number', '-id')
    bom = (query.select_for_update() if lock else query).first()
    if not bom or bom.status != 'VERIFIED' or bom.order_quantity != product.quantity:
        raise ValidationError({'detail': '请先确认与当前订单数量一致的最新 BOM。'})
    link = plan.crafts.filter(removed_at__isnull=True, plan_category=category,
        craft_type_snapshot='INTERNAL', craft__status='ACTIVE').select_related('craft').first()
    if link is None:
        raise ValidationError({'detail': '当前计划没有有效的对应厂内工艺。'})
    kind = 'CUT_PIECE' if category == 'CUTTING' else 'SEWN_PART'
    lines = list(BomLine.objects.filter(section__bom=bom, component_kind=kind)
        .select_related('section', 'parent_part', 'fabric_source_line__section')
        .prefetch_related('cut_pieces__section', 'cut_pieces__fabric_source_line__section').order_by('line_number', 'pk'))
    units = {unit.unit_name: unit for unit in ProductionUnit.objects.filter(status='ACTIVE', archived_at__isnull=True)}
    stock_craft = component_stock_craft(category)
    direct = direct_output_usage(product.pk, kind)
    facts, demands, history = {}, [], []
    for line in lines:
        unit_name = line.unit
        unit = units.get(unit_name)
        if unit is None:
            raise ValidationError({'detail': f'{line.part_name}缺少有效的{unit_name}单位。'})
        key = _key(product.pk, line.component_identity, category)
        if key in facts:
            raise ValidationError({'detail': '同一 BOM 的部位或裁片编号重复。'})
        identity = build_semi_finished_identity(bom_line=line, completed_craft=stock_craft, unit=unit)
        required = component_required_quantity(line, product.quantity)
        used = direct.get(str(line.component_identity), {})
        demands.append(ComponentDemand(str(task.pk), key, key, '片', unit_name, required,
            None, directly_committed=used.get('reserved', 0) + used.get('dispatched', 0)))
        facts[key] = dict(line=line, unit=unit, requirement=None, identity=identity,
            usage=required / product.quantity, material_pair={})
    rows = InternalSemiFinishedReceiptLine.objects.filter(receipt__schedule_product__product_line=product,
        receipt__plan_category=category, bom_line__component_kind=kind).select_related('receipt', 'unit')
    if exclude_receipt_id:
        rows = rows.exclude(receipt_id=exclude_receipt_id)
    for row in rows:
        key = _key(product.pk, row.component_identity, category)
        _receipt_frozen_identity(row, facts.get(key))
        history.append(ReceivedOutput(str(task.pk), key, key, '片', row.unit.unit_name, row.quantity, None))
    args = dict(scope_key=str(task.pk), demands=demands, inputs=[], history=history, check_inputs=False)
    calculation = calculate_receipt(**args) if demands else None
    revision = digest({'bom': str(bom.pk), 'plan': str(plan.pk), 'category': category,
        'demands': [asdict(row) for row in demands], 'history': [asdict(row) for row in history],
        'identities': [fact['identity'] for fact in facts.values()]})
    return dict(part_flow=True, plan=plan, task=task, product=product, bom=bom, craft=link.craft,
        unit=None, category=category, facts=facts, args=args, calculation=calculation,
        revision=revision, sources=[], excluded=[], tube_basis=None)
