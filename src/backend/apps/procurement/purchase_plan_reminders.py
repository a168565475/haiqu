from datetime import date, datetime
from decimal import Decimal

from django.db.models import Min

from apps.core.delivery_reminders import delivery_reminder
from apps.production_scheduling.models import ProductionScheduleProduct

from .tracking_deadlines import coverage_timing
from .tracking_rules import OTHER_ARRIVAL_WINDOW, PIPE_ARRIVAL_WINDOW, arrival_risks


def purchase_window(is_pipe):
    return PIPE_ARRIVAL_WINDOW if is_pipe else OTHER_ARRIVAL_WINDOW


def purchase_unit_key(unit):
    unit = unit.strip().casefold()
    return {"千克": "kg", "公斤": "kg", "米": "m"}.get(unit, unit)


def arrival_reminder(line, *, remaining, unit, today, pipe, shared):
    order = line.purchase_order
    risks = arrival_risks(
        status=order.status, archived=bool(order.archived_at), unreceived=remaining,
        delivery_date=line.delivery_date, is_pipe=pipe, today=today,
        source_reliable=remaining is not None and bool(unit), return_pending=False,
    )
    if risks[0]["code"] in ("ENDED", "ARRIVED"):
        return None
    notes = ["共采批次"] if shared else []
    if line.delivery_date is None and (remaining is None or not unit):
        notes.append("未约定交期")
    return delivery_reminder(
        today=today, window=purchase_window(pipe), due=line.delivery_date,
        quantity=remaining, unit=unit, action="催到货", owner=line.supplier_name_snapshot or "供应商待核",
        reference=order.order_number, review="到货数量待核" if remaining is None or not unit else "",
        reason="，".join(notes), shared=shared,
    )


def scheduled_material_dates(rows):
    product_ids = {row["_bom"].product_line_id for row in rows}
    return dict(ProductionScheduleProduct.objects.filter(
        product_line_id__in=product_ids, schedule__record_status="ACTIVE", removed_at__isnull=True,
    ).order_by().values("product_line_id").annotate(material_date=Min("material_inbound_date")).values_list(
        "product_line_id", "material_date",
    ))


def purchase_shortfalls(row, batches, *, now, category, schedule_dates, policy, unlinked):
    bom = row["_bom"]
    task = bom.production_task
    if task.archived_at or task.status in ("COMPLETED", "CANCELLED"):
        return []
    required = row["required"]
    unit = required["unit"] if required is not None else row["_required_unit"]
    changed = row["_quantity_changed"]
    quantity = Decimal(required["quantity"]) if required is not None and not changed else None
    review = "需求待核" if changed else "需购数量待核" if quantity is None else ""
    if quantity is not None:
        if unlinked or any(batch["shared"] for batch in batches):
            review = "采购归属或分配待核"
        for batch in batches:
            if batch["shared"]:
                continue
            ordered = next((value for value in (batch["ordered"], *batch["ordered_equivalents"])
                            if value is not None and purchase_unit_key(value["unit"]) == purchase_unit_key(unit)), None)
            if ordered is None:
                review = review or "采购数量或单位待核"
            else:
                quantity -= Decimal(ordered["quantity"])
        if quantity <= 0:
            return []
        if review:
            quantity = None

    today = now.date()
    window = purchase_window(category == "TUBE")
    deadlines = []
    no_date_reason = "采购提醒规则未启用"
    if policy is not None:
        timing = coverage_timing(
            now=now, bom_confirmed_at=bom.confirmed_at, bom_verified=bom.status == "VERIFIED",
            scheduled=bom.product_line_id in schedule_dates, material_inbound_date=schedule_dates.get(bom.product_line_id),
            order_delivery_date=task.delivery_date, category_key=category, policy=policy,
        )
        latest = date.fromisoformat(timing["latest_purchase_date"]) if timing["latest_purchase_date"] else None
        bom_due = datetime.fromisoformat(timing["bom_purchase_due_at"]) if timing["bom_purchase_due_at"] else None
        if latest:
            deadlines.append((latest, "最晚采购日"))
        if bom_due and (latest is None or now >= bom_due):
            deadlines.append((bom_due.date(), "BOM 确认后采购期限"))
        no_date_reason = next((risk["label"] for risk in timing["timing_risks"]
                               if risk["code"] in ("SCHEDULE_DATE_UNKNOWN", "PURCHASE_RULE_UNKNOWN", "BOM_CONFIRMATION_UNKNOWN")),
                              "采购期限待核")
    context = {"today": today, "window": window, "quantity": quantity, "unit": unit,
               "action": "待下单", "owner": "采购", "reference": row["bom_number"]}
    if review or not deadlines:
        due = min((day for day, _ in deadlines), default=None)
        return [delivery_reminder(**context, due=due, review=review or no_date_reason,
                                  reason="BOM 用量变更，待核对" if changed else review or no_date_reason)]
    return [delivery_reminder(**context, due=due, reason=reason) for due, reason in deadlines]
