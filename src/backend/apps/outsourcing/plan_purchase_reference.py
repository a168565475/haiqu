"""采购实际入库数量参考，不限制委外需求计划，也不改变库存或保存快照。"""
from decimal import Decimal, ROUND_FLOOR, localcontext

from django.db.models import Prefetch, Q

from apps.boms.models import BomLine
from apps.inventory.models import MaterialInboundLine, MaterialInboundStatus
from apps.procurement.models import PurchaseOrderLine, PurchaseOrderStatus, PurchaseQuantityParseStatus
from apps.procurement.services import _source_quantity

from .tube_kinds import CUTTING_SOURCES


def _matches_source(purchase, source):
    snapshot = purchase.calculation_snapshot or {}
    component = snapshot.get('component_identity')
    if component:
        return str(component) == str(source.component_identity)
    if str(source.pk) in {str(purchase.source_bom_line_id_snapshot), str(purchase.bom_line_id),
                          str(snapshot.get('bom_line_id'))}:
        return True
    return bool(purchase.bom_line_id and purchase.bom_line.component_identity == source.component_identity)


def purchase_reference(line, purchases, *, cutting):
    result = {'quantity': None, 'unit': '套' if cutting else '支', 'purchased_quantity': None,
              'purchase_unit': '米' if cutting else '根', 'conversion_note': ''}
    source = line.fabric_source_line if cutting and line is not None else line
    if source is None:
        result['conversion_note'] = '缺少对应的BOM面料来源。' if cutting else '缺少对应的BOM管材来源。'
        return result
    matched = [purchase for purchase in purchases if _matches_source(purchase, source)]
    quantities = []
    for purchase in matched:
        for inbound in purchase.material_inbound_lines.all():
            if inbound.inbound.status != MaterialInboundStatus.CONFIRMED:
                continue
            if (inbound.inbound.purchase_order_id != purchase.purchase_order_id
                    or not purchase.source_unit_text.strip()
                    or inbound.source_unit_text_snapshot != purchase.source_unit_text
                    or inbound.source_unit_text_snapshot not in {'米', '根'}
                    or (cutting and inbound.source_unit_text_snapshot != '米')):
                result['conversion_note'] = '采购入库来源或数量单位不一致，暂不能换算。'
                return result
            if purchase.material_catalog_id:
                identity_matches = (inbound.material_catalog_id == purchase.material_catalog_id
                    and inbound.material_selection_snapshot == purchase.material_selection_snapshot)
            else:
                raw_id = str((purchase.calculation_snapshot or {}).get('raw_material_id') or '')
                # 旧采购可无材料ID快照；已绑定该采购明细的入库沿用原来源，不另加维护门槛。
                identity_matches = (not inbound.material_catalog_id
                    and (not raw_id or str(inbound.raw_material_information_id or '') == raw_id))
            if not identity_matches:
                result['conversion_note'] = '采购入库材料与采购记录不一致或缺少材料身份，暂不能换算。'
                return result
            # accepted 已扣除质检退货，不能再减退货单或 return_quantity。
            quantity = inbound.accepted_quantity if cutting else inbound.accepted_bar_count
            if quantity is None or quantity < 0:
                result['conversion_note'] = '采购入库记录缺少实际入库米数。' if cutting else '采购入库记录缺少实际入库根数。'
                return result
            quantities.append(quantity)
    with localcontext() as context:
        context.prec = 64
        purchased = sum(quantities, Decimal('0'))
        result['purchased_quantity'] = format(purchased, 'f')
        if cutting:
            bom = source.section.bom
            required, _, _, unit, status = _source_quantity(source, bom)
            if (status != PurchaseQuantityParseStatus.READY or unit.strip() != '米'
                    or required is None or required <= 0 or bom.order_quantity <= 0
                    or not line.cutting_sets_per_product):
                result['conversion_note'] = 'BOM缺少有效的面料每成品用量或裁片每成品套数。'
                return result
            # 按面料整项的每成品用量换算，不能用单个裁片的每套耗米重复分配共用面料。
            per_product = required / bom.order_quantity
            quantity = (purchased * bom.order_quantity * line.cutting_sets_per_product / required
                        ).to_integral_value(rounding=ROUND_FLOOR)
            result['conversion_note'] = (f'采购入库{purchased:f}米 ÷ BOM面料每成品{per_product:f}米'
                                         f' × 每成品{line.cutting_sets_per_product}套，向下取整。')
        else:
            if not line.pieces_per_bar:
                result['conversion_note'] = 'BOM缺少有效的每根切割支数。'
                return result
            quantity = purchased * line.pieces_per_bar
            result['conversion_note'] = f'采购入库{purchased:f}根 × 当前BOM每根{line.pieces_per_bar}支。'
        result['quantity'] = format(quantity, 'f')
    return result


def add_plan_purchase_reference(context, schedule_product):
    lines = {str(line.pk): line for line in BomLine.objects.filter(
        pk__in=[row['bom_line_id'] for row in context['rows']]
    ).select_related('section__bom', 'fabric_source_line__section__bom')}
    purchases = list(PurchaseOrderLine.objects.filter(
        purchase_order__production_task_id=schedule_product.schedule.production_task_id,
        purchase_order__archived_at__isnull=True,
        purchase_order__status__in=[PurchaseOrderStatus.SUBMITTED, PurchaseOrderStatus.PURCHASING,
                                   PurchaseOrderStatus.COMPLETED],
    ).filter(Q(product_line_id_snapshot=schedule_product.product_line_id)
             | Q(product_line_id_snapshot__isnull=True, bom__product_line_id=schedule_product.product_line_id)
    ).select_related('bom_line').prefetch_related(Prefetch(
        'material_inbound_lines', queryset=MaterialInboundLine.objects.select_related('inbound'))))
    cutting = context['source_kind'] in CUTTING_SOURCES
    for row in context['rows']:
        row['purchase_reference'] = purchase_reference(lines.get(row['bom_line_id']), purchases, cutting=cutting)
