"""公共余额只按实物和库区展示；采购与领用原单继续独立追溯。"""
from decimal import Decimal

from django.db.models import Count, Exists, Max, OuterRef, Q, Sum

from apps.workshop_config.models import Craft

from .models import MaterialInboundLine, MaterialStockMovement, PublicStockBalance, PublicStockMovement
from .public_stock_identity import validate_public_identity
from .selectors import material_inventory_rows


def public_raw_inventory_rows(*, keyword="", section_title="", warehouse_id="", zone_id="", location_id=""):
    filters = dict(keyword=keyword, section_title=section_title, warehouse_id=warehouse_id,
                   zone_id=zone_id, location_id=location_id)
    # 普通材料本来就是公共账；旧口径管材不能混进公共根米余额。
    # 库存列表只展示仍有可用余额的记录；零余额仍保留在库存流水和汇总接口中追溯。
    rows = list(material_inventory_rows(**filters).filter(
        measurement_kind="OTHER", inventory_quantity__gt=0,
    ).exclude(raw_material__category__category_name="管材"))
    balances = PublicStockBalance.objects.filter(
        stock_kind="RAW_PIPE", quality="AVAILABLE", quantity__gt=0,
    ).select_related(
        "raw_material__category", "raw_material__color", "unit", "zone__warehouse")
    if keyword:
        matching = MaterialInboundLine.objects.filter(raw_material_information_id=OuterRef("raw_material_id"),
            inbound__status="CONFIRMED", material_pinyin_search__icontains=keyword)
        balances = balances.annotate(inbound_match=Exists(matching)).filter(
            Q(raw_material__material_number__icontains=keyword)
            | Q(raw_material__category__category_name__icontains=keyword)
            | Q(raw_material__material_name__icontains=keyword)
            | Q(raw_material__specification__icontains=keyword)
            | Q(raw_material__material__icontains=keyword) | Q(inbound_match=True))
    if section_title:
        matching = MaterialInboundLine.objects.filter(raw_material_information_id=OuterRef("raw_material_id"),
            inbound__status="CONFIRMED", section_title_snapshot=section_title)
        balances = balances.annotate(section_match=Exists(matching)).filter(
            Q(raw_material__category__category_name=section_title) | Q(section_match=True))
    if warehouse_id:
        balances = balances.filter(zone__warehouse_id=warehouse_id)
    if zone_id:
        balances = balances.filter(zone_id=zone_id)
    if location_id:
        balances = balances.none()
    balances = balances.annotate(
        inbound_count=Count("movements__source_id", distinct=True,
            filter=Q(movements__direction="IN") & ~Q(movements__source_type="PUBLIC_STOCK_OPENING")),
        latest_inbound_time=Max("movements__occurred_at", filter=Q(movements__direction="IN")),
    )
    for balance in balances:
        material, zone = balance.raw_material, balance.zone
        rows.append({
            "measurement_kind": "PIPE", "raw_bar_length_m": balance.raw_bar_length_m,
            "raw_material_id": material.pk, "raw_material__item_type": material.item_type,
            "raw_material__category__category_name": material.category.category_name,
            "raw_material__material_number": material.material_number,
            "raw_material__material_name": material.material_name,
            "raw_material__specification": material.specification, "raw_material__material": material.material,
            "raw_material__color__color_name": material.color.color_name if material.color_id else "",
            "raw_material__color_snapshot": material.color_snapshot,
            "unit__unit_name": balance.unit.unit_name, "zone_id": zone.pk, "zone__zone_name": zone.zone_name,
            "zone__warehouse_id": zone.warehouse_id, "zone__warehouse__warehouse_number": zone.warehouse.warehouse_number,
            "zone__warehouse__warehouse_name": zone.warehouse.warehouse_name,
            "inventory_quantity": balance.quantity, "meter_quantity": balance.meter_quantity,
            "inbound_count": balance.inbound_count, "latest_inbound_time": balance.latest_inbound_time,
        })
    rows.sort(key=lambda row: (str(row["latest_inbound_time"] or ""), str(row["raw_material_id"]), str(row["zone_id"])), reverse=True)
    return rows


def public_pipe_summary(material):
    balances = PublicStockBalance.objects.filter(stock_kind="RAW_PIPE", raw_material=material)
    totals = balances.aggregate(
        available=Sum("quantity", filter=Q(quality="AVAILABLE")),
        meters=Sum("meter_quantity", filter=Q(quality="AVAILABLE")),
        defective=Sum("quantity", filter=Q(quality="DEFECTIVE")),
    )
    old = MaterialStockMovement.objects.filter(balance__raw_material=material, balance__measurement_kind="PIPE")
    current = PublicStockMovement.objects.filter(balance__in=balances).exclude(source_type="PUBLIC_STOCK_OPENING")
    quantities = []
    for query in (old, current):
        quantities.append(query.aggregate(inbound=Sum("quantity", filter=Q(direction="IN")),
                                          issued=Sum("quantity", filter=Q(direction="OUT"))))
    return {
        "stock_item_id": str(material.pk), "material_number": material.material_number,
        "material_name": material.material_name, "category": material.category.category_name,
        "specification": material.specification,
        "color": material.color.color_name if material.color_id else material.color_snapshot,
        "unit": material.unit.unit_name, "stock_kind": "RAW", "measurement_kind": "PIPE",
        "current_quantity": str(totals["available"] or 0), "available_quantity": str(totals["available"] or 0),
        "meter_quantity": str(totals["meters"] or 0), "defective_quantity": str(totals["defective"] or 0),
        "cumulative_inbound_quantity": str(sum((row["inbound"] or Decimal("0") for row in quantities), Decimal("0"))),
        "cumulative_issued_quantity": str(sum((row["issued"] or Decimal("0") for row in quantities), Decimal("0"))),
        "zones": [{
            "zone_id": str(row.zone_id), "balance_id": str(row.pk),
            "warehouse_number": row.zone.warehouse.warehouse_number,
            "warehouse_name": row.zone.warehouse.warehouse_name, "zone_name": row.zone.zone_name,
            "quality": row.quality, "quantity": str(row.quantity), "inbound_line_id": None,
            "raw_bar_length_m": str(row.raw_bar_length_m), "meter_quantity": str(row.meter_quantity),
        } for row in balances.select_related("zone__warehouse").order_by(
            "zone__warehouse__warehouse_number", "zone__zone_name", "raw_bar_length_m", "id")],
    }


def _semi_snapshot(balance):
    return validate_public_identity({
        "stock_kind": balance.stock_kind, "identity_key": balance.identity_key,
        "identity_snapshot": balance.identity_snapshot, "raw_material_id": None,
        "raw_bar_length_m": None, "unit_id": str(balance.unit_id),
    })["identity_snapshot"]


def public_semi_inventory_page(*, page, page_size, keyword="", section_title="", processing_status="", warehouse_id="", zone_id="", location_id=""):
    # 与原材料列表保持一致，零余额不参与库存列表分页和总数统计。
    balances = PublicStockBalance.objects.filter(
        stock_kind="SEMI", quality="AVAILABLE", quantity__gt=0,
    ).select_related("unit", "zone__warehouse")
    if keyword:
        balances = balances.filter(Q(identity_snapshot__part_name__icontains=keyword)
            | Q(identity_snapshot__category__icontains=keyword) | Q(identity_snapshot__material__icontains=keyword)
            | Q(identity_snapshot__specification__icontains=keyword) | Q(identity_snapshot__color__icontains=keyword)
            | Q(identity_snapshot__tube_shape__icontains=keyword) | Q(identity_snapshot__tube_diameter__icontains=keyword))
    if section_title:
        section_kinds = {"型材明细": "PIPE", "管材": "PIPE", "裁剪明细": "CUTTING", "五金件": "HARDWARE"}
        balances = balances.filter(Q(identity_snapshot__category=section_title)
            | Q(identity_snapshot__semi_kind=section_kinds.get(section_title, "")))
    if processing_status:
        balances = balances.filter(identity_snapshot__completed_craft__code=processing_status)
    if warehouse_id:
        balances = balances.filter(zone__warehouse_id=warehouse_id)
    if zone_id:
        balances = balances.filter(zone_id=zone_id)
    if location_id:
        balances = balances.none()
    count = balances.count()
    selected = list(balances.annotate(
        inbound_count=Count("movements__source_id", distinct=True,
            filter=Q(movements__direction="IN") & ~Q(movements__source_type="PUBLIC_STOCK_OPENING")),
        latest_inbound_time=Max("movements__occurred_at", filter=Q(movements__direction="IN")),
    ).order_by("-updated_at", "id")[(page - 1) * page_size:page * page_size])
    snapshots = {row.pk: _semi_snapshot(row) for row in selected}
    craft_ids = {snapshot["completed_craft"]["id"] for snapshot in snapshots.values()}
    crafts = {str(craft.pk): craft.name for craft in Craft.objects.filter(pk__in=craft_ids)}
    rows = []
    for row in selected:
        snapshot = snapshots[row.pk]
        semi_kind = snapshot["semi_kind"]
        specification = snapshot.get("specification", "")
        craft_code = snapshot["completed_craft"]["code"]
        processing_status_label = {"METAL": "未喷塑", "POWDER_COATING": "已喷塑"}.get(
            craft_code, crafts.get(snapshot["completed_craft"]["id"], craft_code))
        if semi_kind == "PIPE":
            specification = (f'{snapshot["tube_shape"]} {snapshot["tube_diameter"]} × {snapshot["tube_thickness"]}mm'
                             f' · 切割 {snapshot["cutting_length_mm"]}mm')
        rows.append({
            "inventory_key": f"SEMI|{row.pk}", "stock_kind": "SEMI", "stock_mode": "PUBLIC_V2", "stock_item_id": "",
            "identity_key": row.identity_key, "identity_snapshot": snapshot,
            "section_type": {"PIPE": "PROFILE", "CUTTING": "FABRIC", "HARDWARE": "ACCESSORY"}[semi_kind],
            "section_title": {"PIPE": "型材明细", "CUTTING": "裁剪明细", "HARDWARE": "五金件"}[semi_kind],
            "category": snapshot["category"], "material_number": "", "material": snapshot["material"],
            "part_name": snapshot["part_name"], "specification": specification, "color": snapshot["color"],
            "completed_craft_code": craft_code, "processing_status": craft_code,
            "processing_status_label": processing_status_label,
            "tube_thickness": snapshot.get("tube_thickness") if semi_kind == "PIPE" else None,
            "cutting_length_mm": snapshot.get("cutting_length_mm") if semi_kind == "PIPE" else None,
            "completed_craft_name": crafts.get(snapshot["completed_craft"]["id"], snapshot["completed_craft"]["code"]),
            "completed_craft": crafts.get(snapshot["completed_craft"]["id"], snapshot["completed_craft"]["code"]),
            "pieces_per_set": snapshot.get("pieces_per_set"), "raw_material": "", "unit": snapshot["unit_name"],
            "inventory_quantity": row.quantity, "raw_bar_length_m": None, "meter_quantity": None,
            "warehouse_id": row.zone.warehouse_id, "warehouse_number": row.zone.warehouse.warehouse_number,
            "warehouse_name": row.zone.warehouse.warehouse_name, "zone_id": row.zone_id, "zone_name": row.zone.zone_name,
            "location_id": None, "location_number": None, "inbound_count": row.inbound_count,
            "latest_inbound_date": row.latest_inbound_time.date() if row.latest_inbound_time else None,
            "latest_inbound_time": row.latest_inbound_time,
            "production_task_number": "", "product_name": "",
        })
    return {"count": count, "next": None, "previous": None, "results": rows}
