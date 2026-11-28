from collections import defaultdict
from decimal import Decimal

from django.db.models import F
from django.utils import timezone

from apps.inventory.models import MaterialInboundLine, MaterialInboundStatus
from apps.inventory.pipe_receipt_basis import is_root_receipt, root_receipt_line_ids
from apps.production_tasks.material_tracking_purchases import purchase_dates

from .purchase_plan_reminders import arrival_reminder, purchase_unit_key


def amount(quantity, unit):
    return {"quantity": format(quantity, "f") if isinstance(quantity, Decimal) else str(quantity),
            "unit": unit} if quantity is not None and unit else None


def amounts(totals):
    return [value for unit, quantity in totals.items() if (value := amount(quantity, unit)) is not None]


def _pipe_amounts(roots, meters, kilograms, primary_unit):
    return [value for quantity, unit in ((roots, "根"), (meters, "米"), (kilograms, "KG"))
            if purchase_unit_key(unit) != purchase_unit_key(primary_unit) and (value := amount(quantity, unit)) is not None]


def _receipt_quantity(receipt, unit, *, pipe, roots, returned=False):
    if roots:
        return receipt.return_bar_count if returned else receipt.received_bar_count
    if pipe and purchase_unit_key(unit) == "kg":
        return receipt.return_weight_kg if returned else receipt.received_weight_kg
    return receipt.return_quantity if returned else receipt.received_quantity


def _batch_receipts(line, receipts, purchase_day, ordered_basis, receipt_unit, *, roots, details):
    pipe = line.section_type_snapshot == "PROFILE"
    counted = Decimal(0)
    usable_roots = 0
    complete_on = None
    arrivals, returns = [], []
    for receipt in receipts:
        inbound = receipt.inbound
        root_receipt = is_root_receipt(receipt)
        actual_unit = "根" if root_receipt else receipt.source_unit_text_snapshot
        if not actual_unit and pipe and receipt.received_weight_kg is not None:
            actual_unit = "KG"
        quantity = _receipt_quantity(receipt, actual_unit, pipe=pipe, roots=root_receipt)
        if not actual_unit or purchase_unit_key(actual_unit) != purchase_unit_key(receipt_unit) or quantity is None:
            counted = None
        status = ""
        if counted is not None:
            if complete_on is not None:
                status = "后续到货"
            counted += quantity
            if ordered_basis is not None and counted >= ordered_basis and complete_on is None:
                complete_on = inbound.inbound_date
                status = "本次到齐"
            if roots:
                usable_roots += receipt.accepted_bar_count if inbound.status == MaterialInboundStatus.CONFIRMED else quantity
        if not details:
            continue
        arrivals.append({
            "id": receipt.pk, "number": inbound.inbound_number, "date": inbound.inbound_date,
            "amount": amount(quantity, actual_unit), "status": status,
            "days": (inbound.inbound_date - purchase_day).days if inbound.inbound_date and purchase_day else None,
            "equivalents": _pipe_amounts(receipt.received_bar_count, receipt.received_quantity,
                                         receipt.received_weight_kg, actual_unit) if pipe and receipt.measurement_kind == "PIPE" else [],
        })

        returned = _receipt_quantity(receipt, actual_unit, pipe=pipe, roots=root_receipt, returned=True)
        return_line = getattr(receipt, "purchase_return_line", None)
        if return_line and (return_line.return_order.inbound_id != inbound.pk or
                            return_line.return_order.purchase_order_id != line.purchase_order_id):
            return_line = None
        if returned or return_line:
            order = return_line.return_order if return_line else None
            confirmed = inbound.quality_confirmed_at
            returns.append({
                "id": receipt.pk, "number": order.return_number if order else inbound.inbound_number,
                "date": timezone.localtime(confirmed).date() if confirmed else None,
                "amount": amount(returned if returned else return_line.quantity, actual_unit),
                "status": order.get_status_display() if order else "质检退货",
                "days": None, "equivalents": [],
            })
    effective = usable_roots if roots and counted is not None else counted
    remaining = max(ordered_basis - effective, 0) if ordered_basis is not None and effective is not None else None
    return arrivals, returns, complete_on, counted, remaining


def purchase_plan_batches(lines, origins, shared_ids, *, today, details):
    if not lines:
        return {}
    published = purchase_dates(lines) if details else {}
    root_ids = root_receipt_line_ids(lines)
    by_purchase_line = defaultdict(list)
    receipts = MaterialInboundLine.objects.filter(
        purchase_order_line_id__in=[line.pk for line in lines],
        inbound__purchase_order_id=F("purchase_order_line__purchase_order_id"),
        inbound__status__in=MaterialInboundStatus.values,
    ).select_related("inbound").order_by("inbound__inbound_date", "inbound__created_at", "pk")
    if details:
        receipts = receipts.select_related("purchase_return_line__return_order")
    for receipt in receipts:
        selection = receipt.material_selection_snapshot or {}
        if selection.get("processing_state") != "PROCESSED":
            by_purchase_line[receipt.purchase_order_line_id].append(receipt)

    batches = {}
    for line in lines:
        order = line.purchase_order
        pipe = line.section_type_snapshot == "PROFILE"
        roots = line.pk in root_ids
        ordered_unit = line.source_unit_text
        receipt_unit = "根" if roots else ordered_unit
        ordered_basis = line.actual_bar_count if roots else line.actual_purchase_quantity
        sheets = published.get((order.pk, str(line.pk)), [])
        if line.supplier_name_snapshot:
            sheets = [item for item in sheets if item[2] == line.supplier_name_snapshot]
        days = {item[0] for item in sheets}
        purchased_on = next(iter(days)) if len(days) == 1 else None
        arrivals, returns, complete_on, received, remaining = _batch_receipts(
            line, by_purchase_line[line.pk], purchased_on, ordered_basis, receipt_unit, roots=roots, details=details,
        )
        batches[line.pk] = {
            "id": line.pk, "order_number": order.order_number, "batch_number": order.batch_number,
            "supplier": line.supplier_name_snapshot, "sheet_numbers": sorted({item[1] for item in sheets}),
            "ordered_on": purchased_on, "expected_on": line.delivery_date, "complete_on": complete_on,
            "ordered": amount(line.actual_purchase_quantity, ordered_unit),
            "ordered_equivalents": _pipe_amounts(line.actual_bar_count, line.actual_purchase_meters,
                                                 line.actual_purchase_weight_kg, ordered_unit) if pipe else [],
            "received": amount(received, receipt_unit),
            "remaining": amount(remaining, receipt_unit),
            "progress": ("待核对" if remaining is None or not receipt_unit else "已到齐" if remaining == 0
                         else "待补收" if roots and complete_on else "未到齐"),
            "reminder": arrival_reminder(line, remaining=remaining, unit=receipt_unit, today=today, pipe=pipe,
                                         shared=line.pk in shared_ids),
            "unit_price": (amount(line.unit_price, ordered_unit) if order.production_task.archived_at is None else None),
            "currency": order.currency_code_snapshot,
            "shared": line.pk in shared_ids,
            **origins[line.pk],
            "arrivals": arrivals, "returns": returns,
        }
    return batches


def purchase_plan_totals(batches, demand_unit):
    if not batches:
        zero = amount(0, demand_unit)
        return ([zero] if zero else [], [zero] if zero else [], "未下单")
    if any(batch["shared"] for batch in batches):
        return [], [], "共采待分配"
    ordered, received = defaultdict(Decimal), defaultdict(Decimal)
    for batch in batches:
        for summary, field in ((ordered, "ordered"), (received, "received")):
            value = batch[field]
            if value is not None:
                summary[value["unit"]] += Decimal(value["quantity"])
    statuses = {batch["progress"] for batch in batches}
    return (
        amounts(ordered) if all(batch["ordered"] is not None for batch in batches) else [],
        amounts(received) if all(batch["received"] is not None for batch in batches) else [],
        next((status for status in ("待核对", "待补收", "未到齐") if status in statuses), "已购到齐"),
    )
