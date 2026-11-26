"""计划分页按部位累计入库判断完成；只作展示，不改订单/报工状态。"""
from collections import defaultdict
from django.db.models import Sum
from apps.boms.models import Bom, BomLine
from apps.outsourcing.sewing_assignments import sewing_part_scopes
from apps.production_scheduling.models import ProductionScheduleProductCraft
from .models import PublicStockMovement
from .internal_receipt_quantities import net_component_demand, ReceiptQuantityError
from .public_stock_mode import public_flow_enabled


def receipt_progress_for_plans(plans, category):
    if category not in {'METAL','CUTTING','SEWING'} or not public_flow_enabled():
        return {}
    product_ids=[plan.product_line_id for plan in plans]
    boms=list(Bom.objects.filter(product_line_id__in=product_ids,archived_at__isnull=True)
        .order_by('product_line_id','-version_number','-id').distinct('product_line_id'))
    latest={bom.product_line_id:bom for bom in boms}
    parts=defaultdict(list)
    for line in BomLine.objects.filter(section__bom_id__in=[bom.pk for bom in boms]).select_related('section', 'parent_part'):
        if line.component_kind:
            if line.component_kind == {'CUTTING': 'CUT_PIECE', 'SEWING': 'SEWN_PART'}.get(category):
                parts[line.section.bom_id].append(line)
            continue
        if category == 'CUTTING':
            continue
        if line.section.section_type=='PROFILE' if category=='METAL' else line.section.section_type=='FABRIC' and line.section.title=='裁剪明细':
            parts[line.section.bom_id].append(line)
    powder=set(ProductionScheduleProductCraft.objects.filter(schedule_product_id__in=[plan.pk for plan in plans],
        removed_at__isnull=True,craft__outsourcing_code='POWDER_COATING').values_list('schedule_product_id',flat=True))
    totals={ (row['product_line_id'],row['bom_line__component_identity'],row['balance__identity_snapshot__completed_craft__code']):row['total']
        for row in PublicStockMovement.objects.filter(product_line_id__in=product_ids,direction='IN',balance__quality='AVAILABLE',
            source_type__in=['INTERNAL_SEMI_RECEIPT','OUTSOURCING_RETURN','METAL_P4_EXTERNAL_RETURN','TUBE_OUTSOURCING_RETURN'])
        .values('product_line_id','bom_line__component_identity','balance__identity_snapshot__completed_craft__code').annotate(total=Sum('quantity')) }
    result={}
    sewing_scopes = sewing_part_scopes([plan.pk for plan in plans]) if category == 'SEWING' else {}
    for plan in plans:
        bom=latest.get(plan.product_line_id)
        lines=parts[bom.pk] if bom else []
        scope = sewing_scopes.get(plan.pk)
        if scope is not None:
            lines = [line for line in lines if str(line.component_identity) in scope]
        complete=0
        if bom and bom.status=='VERIFIED' and bom.order_quantity==plan.product_line.quantity:
            for line in lines:
                try:
                    if scope is not None:
                        required = scope[str(line.component_identity)]
                    elif line.component_kind:
                        from .part_flow_quantities import component_required_quantity
                        required=component_required_quantity(line, plan.product_line.quantity)
                    else:
                        required=net_component_demand(plan.product_line.quantity,line.pieces_per_product if category=='METAL' else line.cutting_sets_per_product)
                except ReceiptQuantityError:
                    continue
                stage='POWDER_COATING' if category=='METAL' and plan.pk in powder else category
                if totals.get((plan.product_line_id,line.component_identity,stage),0)>=required:
                    complete+=1
        result[str(plan.pk)]={'completed_parts':complete,'total_parts':len(lines),'complete':bool(lines) and complete==len(lines)}
    return result
