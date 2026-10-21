"""新建委外单的公共库存候选；GET 不写额度、不读取采购批次。"""
from decimal import Decimal
from types import SimpleNamespace

from apps.products.material_identity import resolve_bom_line_raw_material
from apps.material_issues.public_issue_services import public_issue_quantity_context, public_line_quantities

from .public_stock_services import _lines, _pool, _raws, _requirements, _stock_rows


def enrich_public_candidates(data, line_map, product):
    data["stock_mode"] = "PUBLIC_V2"
    data["batch_selection"] = False
    order = SimpleNamespace(schedule=product.schedule)
    allocation = SimpleNamespace(processing_item=SimpleNamespace(order_product=SimpleNamespace(schedule_product=product)))
    items, by_row = [], {}
    for row in data["material_items"]:
        line = line_map[row["id"]]
        related = next((item.get("conversion_snapshot") for item in data["processing_items"]
            if item.get("conversion_snapshot") and item["conversion_snapshot"].get("material_line_id") == row["id"]), None)
        if related is None:
            raw, _ = resolve_bom_line_raw_material(line)
            related = {"kind": "OTHER", "raw_material_id": str(raw.pk)} if raw else None
        row.update(candidates=[], zones=[], batch_selection=False)
        if related is None:
            continue
        if related.get("quantity_basis") == "OUTPUT_SETS":
            related = {**related, "input_unit": related["raw_input_unit"]}
        item = SimpleNamespace(pk=line.pk, bom_material_line_id=line.pk, conversion_snapshot=related,
            allocation=allocation, planned_piece_count=Decimal(related.get("allowance_pieces", 0)),
            planned_issue_quantity=Decimal(0))
        items.append(item)
        by_row[line.pk] = row
    if not items:
        return
    requirements = _requirements(order, items)
    # 无有效额度的候选仍展示原有错误，不因一条未就绪原料使整页消失。
    items = [item for item in items if item.bom_material_line_id in requirements]
    if not items:
        return
    issue, lines = _lines(order, items, requirements, _raws(items))
    context = public_issue_quantity_context(issue, lines=list(lines.values()))
    balances = _stock_rows(context, lines.values())
    for item in items:
        line, row = lines[item.pk], by_row[item.pk]
        values = public_line_quantities(line, context=context)
        is_pipe = item.conversion_snapshot["kind"] == "PIPE"
        factor = Decimal(item.conversion_snapshot["pieces_per_bar"]) if is_pipe else Decimal(1)
        row.update(**values, conversion_snapshot=line.conversion_snapshot)
        row["zones"] = [{"zone_id": str(b.zone_id), "zone_name": b.zone.zone_name,
            "warehouse_name": b.zone.warehouse.warehouse_name, "available_quantity": str(b.quantity),
            "available_input_quantity": str(b.quantity * factor),
            "available_meters": str(b.meter_quantity) if is_pipe else None} for b in balances[_pool(line)]]
        if is_pipe:
            row.update(default_issue_quantity=values["max_issue_quantity"], reference_required_quantity=values["order_remaining"])
        for processing in data["processing_items"]:
            snapshot = processing.get("conversion_snapshot") or {}
            if snapshot.get("material_line_id") == str(item.pk) and snapshot.get("quantity_basis") != "OUTPUT_SETS":
                processing["available_quantity"] = values["order_remaining"]
