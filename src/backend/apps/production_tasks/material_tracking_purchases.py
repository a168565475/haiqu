"""Track purchase documents and first complete receipt per fabric specification."""
from collections import Counter, defaultdict
from datetime import date
from decimal import Decimal

from django.db.models import F, Q
from rest_framework.exceptions import ValidationError

from apps.boms.models import BomLine, BomStatus
from apps.inventory.bom_inventory_sections import RAW_SECTIONS
from apps.inventory.models import MaterialStockMovement, PublicStockMovement
from apps.inventory.purchase_receiving_sections import with_receiving_section
from apps.inventory.selectors import stock_receipt_source_lines
from apps.procurement.group_services import bom_group_line_snapshot
from apps.procurement.models import PurchaseOrderLine, PurchaseOrderStatus, SupplierPurchaseSheet, SupplierPurchaseSheetStatus
from apps.procurement.multi_bom_sources import purchase_merge_key
from apps.procurement.selectors import purchase_line_products
from apps.procurement.services import _is_purchasable_bom_section, _source_line, is_hardware_weight_snapshot

from .material_tracking import add_batch, quantity_text

CATEGORIES = {"TUBE": "steel", "FABRIC": "fabric", "PLASTIC": "plastic", "HARDWARE": "hardware", "PACKAGING": "packaging"}
METER_UNITS = {"米", "m", "M"}


def fabric_key(snapshot):
    if snapshot["source_unit_text"] not in METER_UNITS:
        return None
    try:
        material, _, _, attrs, *_ = purchase_merge_key({**snapshot, "source_unit_text": "米"})
    except ValidationError:
        return None
    return material, attrs


def fabric_demand(products, boms):
    ready = {bom.pk: product for product in products if (bom := boms.get(product.pk))
             and bom.status == BomStatus.VERIFIED and bom.order_quantity == product.quantity}
    demand = defaultdict(Counter)
    labels, incomplete = {}, set()
    fabric_titles = RAW_SECTIONS["FABRIC"][1]
    lines = BomLine.objects.filter(section__bom_id__in=ready).select_related("section__bom")
    for line in lines:
        section = line.section
        if not _is_purchasable_bom_section(section) or not line.purchase_required:
            continue
        selection = line.material_selection_snapshot or {}
        category = selection.get("category_key")
        if category and category != "FABRIC":
            continue
        if not category and section.title.strip() not in fabric_titles and line.category.strip() not in fabric_titles:
            continue
        if selection.get("processing_state") == "PROCESSED" or selection.get("template_key") in {"COTTON", "AUXILIARY_GENERAL"}:
            continue
        product = ready[section.bom_id]
        source = _source_line(section.bom, section, line, product)
        try:
            key = fabric_key(bom_group_line_snapshot(source))
        except ValidationError:
            key = None
        quantity = source["required_quantity"]
        if key is None or quantity is None or quantity <= 0:
            incomplete.add(product.pk)
            continue
        demand[product.pk][key] += quantity
        labels[(product.pk, key)] = selection.get("display_name") or " / ".join(
            filter(None, (line.material or line.part_name, line.specification, line.raw_material)),
        )
    return demand, labels, incomplete


def purchase_dates(lines):
    dates = defaultdict(list)
    for sheet in SupplierPurchaseSheet.objects.filter(
        purchase_order_id__in={line.purchase_order_id for line in lines},
        status=SupplierPurchaseSheetStatus.PUBLISHED, archived_at__isnull=True,
    ).order_by("series_id", "-version_number", "-pk").distinct("series_id"):
        contents = sheet.content_snapshot
        try:
            purchase_date = date.fromisoformat(contents.get("purchase_date", ""))
        except (TypeError, ValueError):
            continue
        for item in contents.get("lines", []):
            line_id = item.get("source_purchase_order_line_id")
            if line_id:
                dates[(sheet.purchase_order_id, str(line_id))].append(
                    (purchase_date, sheet.sheet_number, sheet.supplier_name_snapshot))
    return dates


def first_complete(required, by_date):
    received = Decimal("0")
    for day, quantity in sorted(by_date.items()):
        received += quantity
        if received >= required:
            return day
    return None


def purchase_batches(products, boms, batches):
    products_by_id = {str(product.pk): product for product in products}
    orders = with_receiving_section(PurchaseOrderLine.objects.filter(
        purchase_order__production_task_id__in={product.production_task_id for product in products},
        purchase_order__source_type="PRODUCTION",
    ).exclude(purchase_order__status=PurchaseOrderStatus.DRAFT)).filter(receiving_section__in=CATEGORIES)
    lines = list(orders.select_related("purchase_order", "bom").order_by())
    sheet_dates = purchase_dates(lines)
    eligible = {}
    for line in lines:
        order = line.purchase_order
        source_ids = {source[0] for source in purchase_line_products(line)}
        if line.bom_id and len(source_ids) == 1:
            if line.bom.production_task_id != order.production_task_id:
                continue
            if source_ids == {""}:
                source_ids = {str(line.bom.product_line_id)}
            elif str(line.bom.product_line_id) not in source_ids:
                continue
        belongs = [products_by_id[key].pk for key in source_ids if key in products_by_id
                   and products_by_id[key].production_task_id == order.production_task_id]
        if not belongs:
            continue
        category = line.receiving_section
        selected = line.material_selection_snapshot or {}
        if category == "FABRIC" and (selected.get("processing_state") == "PROCESSED"
                                   or selected.get("template_key") in {"COTTON", "AUXILIARY_GENERAL"}):
            continue
        material = selected.get("display_name") or " / ".join(
            filter(None, (line.material_snapshot or line.part_name_snapshot, line.specification_snapshot)),
        )
        shared = len(source_ids) != 1
        eligible[line.pk] = (line, category, material, belongs, shared)
        published = sheet_dates[(order.pk, str(line.pk))]
        for product_id in belongs:
            for day, number, supplier in published or [(None, order.order_number, line.supplier_name_snapshot)]:
                note = "共采待分配" if shared else ""
                if not day and not note:
                    note = "未见已发布采购日期"
                add_batch(batches[product_id], CATEGORIES[category] + "_purchase", day, number, party=supplier,
                          material=material, quantity=None if shared else line.actual_purchase_quantity,
                          unit="" if shared else line.source_unit_text, note=note)

    demand, labels, incomplete = fabric_demand(products, boms)
    received = defaultdict(Counter)
    shared_fabric = set()
    receipts = (stock_receipt_source_lines(MaterialStockMovement) | stock_receipt_source_lines(PublicStockMovement))
    receipts = receipts.filter(
        Q(accepted_quantity__gt=0) | Q(accepted_weight_kg__gt=0),
        purchase_order_line_id__in=eligible, inbound__purchase_order_id=F("purchase_order_line__purchase_order_id"),
    ).select_related("inbound").order_by()
    for row in receipts:
        line, category, material, belongs, shared = eligible[row.purchase_order_line_id]
        if category == "TUBE":
            continue
        kind = "fabric_arrival" if category == "FABRIC" else CATEGORIES[category] + "_receipt"
        unit = row.source_unit_text_snapshot
        weighted = category == "HARDWARE" and is_hardware_weight_snapshot(row.calculation_snapshot)
        accepted = row.accepted_weight_kg if weighted else row.accepted_quantity
        for product_id in belongs:
            add_batch(batches[product_id], kind, None if shared else row.inbound.inbound_date, row.inbound.inbound_number,
                      party=row.supplier_name_snapshot, material=material, quantity=None if shared else accepted,
                      unit="" if shared else unit, note="共采待分配" if shared else "")
            if category != "FABRIC":
                continue
            if shared:
                shared_fabric.add(product_id)
                continue
            calculation = line.calculation_snapshot or {}
            if row.raw_material_information_id:
                raw_id = str(row.raw_material_information_id)
                if calculation.get("raw_material_id") and calculation["raw_material_id"] != raw_id:
                    continue
                calculation = {**calculation, "raw_material_id": raw_id}
            selected = row.material_selection_snapshot or line.material_selection_snapshot
            key = fabric_key({
                "material_catalog_id": row.material_catalog_id or line.material_catalog_id,
                "material_selection_snapshot": selected, "calculation_snapshot": calculation,
                "section_type_snapshot": line.section_type_snapshot, "section_title_snapshot": line.section_title_snapshot,
                "material_attributes_snapshot": row.material_attributes_snapshot, "source_unit_text": unit,
            })
            if key in demand[product_id]:
                received[(product_id, key)][row.inbound.inbound_date] += row.accepted_quantity

    result = {}
    for product in products:
        pk = product.pk
        fabrics = []
        for key, required in demand[pk].items():
            arrivals = received[(pk, key)]
            fabrics.append({
                "material": labels[(pk, key)], "required": quantity_text(required), "unit": "米",
                "arrived_on": first_complete(required, arrivals), "total_received": quantity_text(sum(arrivals.values())),
            })
        note = ""
        day = None
        if pk in incomplete:
            note = "布料需求待核对"
        elif len(fabrics) > 1:
            note = f"{sum(bool(item['arrived_on']) for item in fabrics)}/{len(fabrics)} 规格到齐"
        elif fabrics:
            day = fabrics[0]["arrived_on"]
            if day is None:
                note = "共采待分配" if pk in shared_fabric else "未到齐"
        elif any(event["kind"] in ("fabric_purchase", "fabric_arrival") for event in batches[pk]):
            note = "布料需求待核对"
        result[pk] = fabrics, day, note
    return result
