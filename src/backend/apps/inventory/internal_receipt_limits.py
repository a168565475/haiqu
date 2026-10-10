"""公共入账最后一道门禁：厂内与外发同部位同阶段共同使用订单产出额度。"""
from django.db.models import Sum
from apps.boms.models import Bom, BomLine
from apps.production_tasks.models import ProductionTaskProduct
from .models import InternalSemiFinishedReceipt, InternalSemiFinishedReceiptLine, PublicStockMovement
from .internal_receipt_quantities import net_component_demand
from .stock_services import InventoryStockValidationError


def validate_combined_output(*, source, identity, quantity, quality):
    types = ['INTERNAL_SEMI_RECEIPT','OUTSOURCING_RETURN','METAL_P4_EXTERNAL_RETURN']
    if source['source_type'] not in types or identity['stock_kind'] != 'SEMI' or quality != 'AVAILABLE':
        return
    line = BomLine.objects.filter(pk=source['bom_line_id']).first()
    product = ProductionTaskProduct.objects.filter(pk=source['product_line_id']).first()
    if not line or not product:
        return  # 来源完整性由公共记账服务处理。
    stage = identity['identity_snapshot']['completed_craft']['code']
    if source['source_type'] == 'INTERNAL_SEMI_RECEIPT' and stage == 'METAL':
        from apps.outsourcing.models import TubeOutsourcingLine
        pending = TubeOutsourcingLine.objects.filter(order__product_line=product,
                order__source_kind='METAL', order__status__in=['PENDING_DISPATCH', 'PROCESSING', 'COMPLETED']).exists()
        report_based = InternalSemiFinishedReceipt.objects.filter(schedule_product__product_line=product,
            source_snapshot__quantity_basis='WORK_REPORT_MINIMUM').exists()
        if pending or report_based:
            # 这里已经持有父对象锁，仅只读复核，不能反向取得领料/计划锁。
            from .tube_processing_services import metal_component_limits, _basis_dates
            current = metal_component_limits(product)
            basis = current['components'].get(str(line.component_identity))
            unmatched = PublicStockMovement.objects.filter(product_line=product,
                bom_line__component_identity=line.component_identity, direction='IN',
                source_type='INTERNAL_SEMI_RECEIPT', balance__quality='AVAILABLE',
                balance__identity_snapshot__completed_craft__code='METAL').exclude(
                    pk__in=InternalSemiFinishedReceiptLine.objects.values('stock_movement_id')).aggregate(total=Sum('quantity'))['total'] or 0
            remaining = max(basis['allowance']['remaining'] - unmatched, 0) if basis and basis['basis_ready'] else 0
            for day in _basis_dates(product.pk):
                if str(day) == current['as_of']:
                    continue
                future = metal_component_limits(product, as_of=day)['components'].get(str(line.component_identity))
                allowed = max(future['allowance']['reported_minimum'] - future['allowance']['report_protected_usage'] - unmatched, 0) if future and future['basis_ready'] else 0
                remaining = min(remaining, allowed)
            if not basis or not basis['basis_ready'] or quantity > remaining:
                raise InventoryStockValidationError({'detail':'本次入库超过报工、有效投入和已处理预留共同支持的剩余额度，请刷新核对。'},
                    code='TUBE_OUTSOURCING_OUTPUT_RESERVED' if pending else 'TUBE_REPORT_OUTPUT_LIMIT')
    internal = InternalSemiFinishedReceiptLine.objects.filter(receipt__schedule_product__product_line=product,
        component_identity=line.component_identity,attribute_snapshot__completed_craft__code=stage)
    if source['source_type'] != 'INTERNAL_SEMI_RECEIPT' and not internal.exists():
        return  # 尚未使用厂内新流程的旧外发单继续原有数量门禁。
    latest = Bom.objects.filter(product_line=product,archived_at__isnull=True).order_by('-version_number','-id').first()
    targets = list(BomLine.objects.filter(section__bom=latest,component_identity=line.component_identity))
    if not latest or latest.status != 'VERIFIED' or latest.order_quantity != product.quantity or len(targets)!=1:
        raise InventoryStockValidationError({'detail':'厂内及外发共同入库需使用当前已确认的唯一 BOM 部位。'},code='INTERNAL_RECEIPT_BOM_CHANGED')
    target=targets[0]
    required=net_component_demand(product.quantity,target.pieces_per_product if stage=='METAL' else target.cutting_sets_per_product)
    total=PublicStockMovement.objects.filter(production_task_id=source['production_task_id'],product_line=product,
        bom_line__component_identity=line.component_identity,direction='IN',source_type__in=types,
        balance__quality='AVAILABLE',balance__identity_snapshot__completed_craft__code=stage).aggregate(total=Sum('quantity'))['total'] or 0
    if total+quantity>required:
        raise InventoryStockValidationError({'detail':'厂内及外发累计入库超过该部位 BOM 单个用量 × 订单数量。'},code='INTERNAL_RECEIPT_DEMAND_EXCEEDED')
