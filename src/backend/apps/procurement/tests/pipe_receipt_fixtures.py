from django.utils import timezone

from apps.inventory.models import MaterialInbound, MaterialInboundLine
from apps.procurement.models import PurchaseReturn, PurchaseReturnLine


def historical_weighed_return(line, zone_id, *, raw_material=None):
    """一根实称一公斤的旧送货已全退，后续仍可收原订单的全部数量。"""
    order = line.purchase_order
    actor = order.created_by_employee
    now = timezone.now()
    inbound = MaterialInbound.objects.create(inbound_number="OLD-PIPE-IN", purchase_order=order,
        stock_mode="PUBLIC_V2" if line.material_catalog_id else "LEGACY", status="CONFIRMED",
        received_by_employee=actor, quality_confirmed_by_employee=actor, quality_confirmed_at=now)
    receipt = MaterialInboundLine.objects.create(inbound=inbound, purchase_order_line=line, zone_id=zone_id,
        raw_material_information=raw_material, material_catalog_id=line.material_catalog_id,
        material_selection_snapshot=line.material_selection_snapshot, measurement_kind="PIPE",
        raw_bar_length_m=line.raw_bar_length_m, bar_weight_kg=line.raw_bar_weight_kg,
        received_bar_count=1, accepted_bar_count=0, return_bar_count=1,
        received_weight_kg=1, accepted_weight_kg=0, return_weight_kg=1,
        received_quantity=line.raw_bar_length_m, accepted_quantity=0, return_quantity=line.raw_bar_length_m,
        source_unit_text_snapshot=line.source_unit_text, purchased_quantity_snapshot=line.actual_purchase_quantity)
    returned = PurchaseReturn.objects.create(return_number="OLD-PIPE-RT", inbound=inbound,
        purchase_order=order, supplier=line.supplier, supplier_number_snapshot=line.supplier_number_snapshot,
        supplier_name_snapshot=line.supplier_name_snapshot, status="COMPLETED", generated_by_employee=actor,
        confirmed_by_employee=actor, completed_by_employee=actor, confirmed_at=now, completed_at=now)
    PurchaseReturnLine.objects.create(return_order=returned, inbound_line=receipt, quantity=1)
    return receipt
