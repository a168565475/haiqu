"""按工序、部位和加工点汇总布面委外进度。"""
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from itertools import chain
from uuid import UUID

from django.db.models import F, Q, Sum

from apps.access_control.module_operations import CUT_PIECE_PRINTING
from apps.access_control.resource_scopes import filter_crafts
from apps.access_control.sales_policy import has_permission
from apps.core.delivery_reminders import business_today, delivery_reminder, matching_reminder, reminder_matches, reminder_order
from apps.production_tasks.models import ProductionTaskProduct
from .legacy_raw_returns import raw_returns_by_dispatch
from .models import (
    OutsourcingDispatchLine, OutsourcingFactory, OutsourcingFactoryAllocation, OutsourcingMaterialItem,
    OutsourcingReturnLine, TubeOutsourcingLine, TubeOutsourcingOrder,
)
from .printed_pieces import processor_transfer_quantities
from .selectors import accessible_outsourcing_orders
from .sewing_workbench import RETURN_REMINDER_DAYS, receipt_lines, shipment_rows
from .tube_kinds import CUTTING_SOURCES
from .tube_selectors import (
    VIEW_PERMISSION, printing_product_lines, product_display, saved_orders_for_permission, visible_products,
)
from .unified_selectors import workshop_regular_access


TRACKED_CRAFTS = ("SEWING", "SCREEN_PRINTING")
QUANTITY_FIELDS = ("sent", "received", "factory_remaining", "not_sent", "transferred")


@dataclass(frozen=True)
class PartProgress:
    product: ProductionTaskProduct
    process: str
    schedule_product_id: UUID | None
    factory_id: UUID
    factory_name: str
    part_id: UUID
    name: str
    unit_price: Decimal | None
    price_unit: str
    planned_dispatch_date: date | None
    dispatch_dates: set[date]
    expected_return_date: date
    last_receipt_date: date | None
    unit: str
    assigned: int | Decimal
    sent: int | Decimal | None
    sent_for_return: int | Decimal | None
    received: int | Decimal | None
    order_number: str
    open_for_follow_up: bool
    transferred: int = 0


def complete_parts(recipe, sent):
    if not sent:
        return 0
    if not recipe or sent.keys() - recipe.keys():
        return None
    # 同一部位的每种裁片先跨批加总，再按最短缺的一种折算。
    return min(sent.get(piece, 0) // per_part for piece, per_part in recipe.items())


def fabric_meters_per_set(snapshot):
    try:
        ratio = Decimal(str(snapshot.get("fabric_meters_per_set")))
    except InvalidOperation:
        return None
    return ratio if ratio.is_finite() and ratio > 0 else None


def tube_part_progress(request, task_number, *, regular):
    printing = saved_orders_for_permission(request, CUT_PIECE_PRINTING)
    authorized = Q(pk__in=printing.values("pk"))
    if regular:
        workshop = filter_crafts(saved_orders_for_permission(request), request, VIEW_PERMISSION)
        authorized |= Q(pk__in=workshop.values("pk"))
    roots = TubeOutsourcingOrder.objects.filter(
        authorized, plan__isnull=True, craft__outsourcing_code__in=TRACKED_CRAFTS,
        product_line__production_task__task_number__icontains=task_number,
    ).exclude(status="CANCELLED").order_by()
    ids = roots.values("pk")
    piece_shipments, whole_shipments = shipment_rows(ids)
    pieces, piece_dates = defaultdict(Counter), defaultdict(set)
    dispatch_day = "order__actions__actual_dispatch_date"
    for parent, piece, day, amount in piece_shipments.filter(
        parent_line__order_id=F("root"), factory_id=F("parent_line__factory_id"),
    ).values("parent_line_id", "component_identity", dispatch_day).annotate(amount=Sum("quantity")).values_list(
        "parent_line_id", "component_identity", dispatch_day, "amount",
    ).iterator():
        pieces[parent][str(piece)] += amount
        piece_dates[parent].add(day)

    whole, whole_dates = defaultdict(Counter), defaultdict(set)
    for root, factory, part, unit, day, amount in whole_shipments.filter(
        root__in=roots.exclude(source_snapshot__contains={"sewing_inputs": True}).values("pk"),
    ).values("root", "factory_id", "component_identity", "snapshot__unit", dispatch_day).annotate(amount=Sum("quantity")).values_list(
        "root", "factory_id", "component_identity", "snapshot__unit", dispatch_day, "amount",
    ).iterator():
        whole[root, part][factory, unit] += amount
        whole_dates[root, part, factory].add(day)

    received, receipt_dates = Counter(), {}
    for root, line_id, _, _, _, quantity, _, day in receipt_lines(ids):
        key = root, line_id
        received[key] += quantity
        receipt_dates[key] = max(day, receipt_dates.get(key, day))
    transfers = processor_transfer_quantities(roots.filter(
        source_snapshot__contains={"screen_print_pieces": True},
    ).values("pk"))

    lines = TubeOutsourcingLine.objects.filter(order_id__in=ids).select_related(
        "order__product_line__production_task", "order__craft", "factory", "bom_line",
    ).order_by("-order__created_at", "order_id", "bom_line__line_number", "id")
    for line in lines.iterator():
        order = line.order
        uses_pieces = order.source_snapshot.get("sewing_inputs") or line.pk in pieces
        historical_unit = "套" if not uses_pieces and order.source_kind in CUTTING_SOURCES else ""
        unit = line.snapshot.get("unit") or historical_unit
        if uses_pieces:
            recipe = {}
            for piece in line.snapshot.get("pieces") or []:
                identity, ratio = piece.get("component_identity"), piece.get("pieces_per_part")
                if not identity or not isinstance(ratio, int) or ratio <= 0 or identity in recipe:
                    recipe = {}
                    break
                recipe[identity] = ratio
            sent = complete_parts(recipe, pieces[line.pk])
            actual_dates = piece_dates[line.pk]
        else:
            shipments = whole[order.pk, line.component_identity]
            attributable = all(
                factory == line.factory_id and (saved_unit or historical_unit) == unit
                for factory, saved_unit in shipments
            )
            sent = sum(shipments.values()) if attributable else None
            actual_dates = whole_dates[order.pk, line.component_identity, line.factory_id]
        key = order.pk, line.pk
        yield PartProgress(
            product=order.product_line, process=order.craft.outsourcing_code,
            schedule_product_id=order.schedule_product_id, factory_id=line.factory_id,
            factory_name=line.snapshot.get("factory_name") or line.factory.name,
            part_id=line.component_identity,
            name=line.snapshot.get("part_name") or line.bom_line.part_name,
            unit_price=line.unit_price, price_unit="㎡" if line.price_unit == "SQUARE_METER" else unit,
            planned_dispatch_date=order.planned_dispatch_date, dispatch_dates=actual_dates,
            expected_return_date=order.expected_return_date, last_receipt_date=receipt_dates.get(key),
            unit=unit, assigned=line.quantity, sent=sent, sent_for_return=sent,
            received=received[key], transferred=transfers.get(line.pk, 0),
            order_number=order.order_number, open_for_follow_up=order.status not in ("COMPLETED", "CLOSED"),
        )


def historical_part_progress(request, task_number):
    orders = filter_crafts(accessible_outsourcing_orders(request, VIEW_PERMISSION), request, VIEW_PERMISSION).filter(
        craft__outsourcing_code__in=TRACKED_CRAFTS, schedule__production_task__task_number__icontains=task_number,
    ).exclude(status="CANCELLED").order_by()
    allocation_path = "processing_item__order_product__order_id"
    allocations = OutsourcingFactoryAllocation.objects.filter(**{f"{allocation_path}__in": orders.values("pk")})
    recipes = defaultdict(dict)
    materials = OutsourcingMaterialItem.objects.filter(allocation__in=allocations, conversion_snapshot__kind="FABRIC")
    for allocation, material, unit, snapshot in materials.values_list(
        "allocation_id", "pk", "unit_text", "conversion_snapshot",
    ).iterator():
        recipes[allocation][material] = fabric_meters_per_set(snapshot) if unit == "米" else None

    sent, net_sent = defaultdict(Counter), defaultdict(Counter)
    issued_allocations, issued_orders = set(), set()
    incomplete, uncertain_raw_returns = set(), set()
    dispatches = OutsourcingDispatchLine.objects.filter(
        material_item__allocation__in=allocations, dispatch__order_id=F(f"material_item__allocation__{allocation_path}"),
    )
    raw_returns = raw_returns_by_dispatch(dispatches)
    for line_id, order, allocation, material, amount, unit, snapshot in dispatches.values_list(
        "pk", "dispatch__order_id", "material_item__allocation_id", "material_item_id", "issued_quantity",
        "unit__unit_name", "snapshot",
    ).iterator():
        issued_orders.add(order)
        issued_allocations.add(allocation)
        recipe = recipes[allocation]
        if snapshot.get("kind") == "FABRIC" or material in recipe:
            saved_ratio = recipe.get(material)
            ratio = fabric_meters_per_set(snapshot) or saved_ratio
            if unit == "米" and ratio and (saved_ratio is None or ratio == saved_ratio):
                recipe[material] = ratio
                sent[allocation][material] += amount
                returned_meters = sum(meters if meters is not None else quantity
                                      for quantity, meters, _ in raw_returns.get(line_id, ()))
                if returned_meters > amount:
                    uncertain_raw_returns.add(allocation)
                else:
                    net_sent[allocation][material] += amount - returned_meters
            else:
                incomplete.add(allocation)

    returned, dates = Counter(), {}
    unknown_returns = set()
    for allocation, assigned_factory, saved_factory, amount, day in OutsourcingReturnLine.objects.filter(
        allocation__in=allocations, return_record__order_id=F(f"allocation__{allocation_path}"), returned_quantity__gt=0,
    ).values_list("allocation_id", "allocation__factory_id", "return_record__factory_id", "returned_quantity",
                  "return_record__return_date").iterator():
        if saved_factory and assigned_factory != saved_factory:
            unknown_returns.add(allocation)
            continue
        returned[allocation] += amount
        dates[allocation] = max(day, dates.get(allocation, day))

    for allocation in allocations.select_related(
        "processing_item__order_product__order__dispatch_record", "processing_item__order_product__order__craft",
        "processing_item__order_product__schedule_product__product_line__production_task", "processing_item__bom_line", "factory",
    ).order_by("-processing_item__order_product__order__created_at", "id").iterator():
        item = allocation.processing_item
        order_product = item.order_product
        order = order_product.order
        dispatch = getattr(order, "dispatch_record", None)
        recipe = recipes[allocation.pk]
        if not dispatch or (order.pk in issued_orders and allocation.pk not in issued_allocations):
            sent_parts = sent_for_return = 0
        elif item.unit_snapshot == "套" and allocation.pk not in incomplete and recipe and all(recipe.values()):
            sent_parts = complete_parts(recipe, sent[allocation.pk])
            sent_for_return = (None if allocation.pk in uncertain_raw_returns
                               else complete_parts(recipe, net_sent[allocation.pk]))
        else:
            sent_parts = sent_for_return = None
        yield PartProgress(
            product=order_product.schedule_product.product_line, process=order.craft.outsourcing_code,
            schedule_product_id=order_product.schedule_product_id,
            factory_id=allocation.factory_id, factory_name=allocation.factory_snapshot.get("name") or allocation.factory.name,
            part_id=item.bom_line.component_identity,
            name=item.component_snapshot.get("part_name") or item.bom_line.part_name,
            unit_price=allocation.unit_price, price_unit=item.unit_snapshot,
            planned_dispatch_date=None,
            dispatch_dates={dispatch.dispatch_date} if dispatch and allocation.pk in issued_allocations else set(),
            expected_return_date=order.delivery_date, last_receipt_date=dates.get(allocation.pk),
            unit=item.unit_snapshot, assigned=allocation.allocated_quantity, sent=sent_parts, sent_for_return=sent_for_return,
            received=None if allocation.pk in unknown_returns else returned[allocation.pk],
            order_number=order.order_number, open_for_follow_up=order.status not in ("COMPLETED", "CLOSED"),
        )


def sewing_tracking_rows(request, task_number, *, follow_up="ALL", owner=""):
    today = business_today()
    regular = workshop_regular_access(request)
    parts = tube_part_progress(request, task_number, regular=regular)
    if regular:
        parts = chain(parts, historical_part_progress(request, task_number))
    groups = {}
    for part in parts:
        product = part.product
        color = product.color_name_snapshot or product.customer_color_snapshot or product.color_code_snapshot
        color_key = (product.color_card_snapshot, product.color_code_snapshot) if product.color_code_snapshot else (
            product.product_color_id or color,
        )
        style = (product.product_catalog_id or product.product_id
                 or product.product_code_snapshot or product.product_number_snapshot or product.pk)
        key = product.production_task_id, style, color_key, part.process, part.factory_id, part.part_id
        row = groups.setdefault(key, {
            "id": f"{product.pk}:{part.process}:{part.factory_id}:{part.part_id}",
            "task_number": product.production_task.task_number, "process": part.process,
            "product_name": product.product_name_snapshot or product.customer_product_name_snapshot, "color": color,
            "factory_id": part.factory_id, "factory_name": part.factory_name, "product_ids": {}, "schedule_product_ids": {},
            "part_name": part.name, "unit_prices": set(), "dispatch_dates": set(),
            "planned_dispatch_dates": set(), "expected_return_dates": set(),
            "last_receipt_date": None, "_reminders": [], **{field: {} for field in QUANTITY_FIELDS},
        })
        row["product_ids"][product.pk] = None
        row["schedule_product_ids"][part.schedule_product_id] = None
        if part.unit_price is not None:
            row["unit_prices"].add((part.unit_price, part.price_unit))
        row["dispatch_dates"].update(part.dispatch_dates)
        if part.planned_dispatch_date:
            row["planned_dispatch_dates"].add(part.planned_dispatch_date)
        if part.expected_return_date:
            row["expected_return_dates"].add(part.expected_return_date)
        if part.last_receipt_date:
            row["last_receipt_date"] = max(part.last_receipt_date, row["last_receipt_date"] or part.last_receipt_date)
        owed = (None if part.sent_for_return is None or part.received is None
                else max(part.sent_for_return - part.received - part.transferred, 0))
        unsent = None if part.sent is None else max(part.assigned - part.sent, 0)
        if part.open_for_follow_up:
            context = {"today": today, "window": RETURN_REMINDER_DAYS, "unit": part.unit, "reference": part.order_number}
            if part.sent != 0:
                row["_reminders"].append(delivery_reminder(
                    **context, due=part.expected_return_date, quantity=owed, action="催回厂", owner=part.factory_name,
                ))
            if part.planned_dispatch_date and unsent is not None:
                row["_reminders"].append(delivery_reminder(
                    **context, due=part.planned_dispatch_date, quantity=unsent, action="我方待发", owner="我方",
                ))
        for field, value in zip(QUANTITY_FIELDS, (part.sent, part.received, owed, unsent, part.transferred), strict=True):
            if field == "transferred" and not value:
                continue
            totals = row[field]
            previous = totals.get(part.unit, 0)
            totals[part.unit] = None if previous is None or value is None or not part.unit else previous + value

    selected = []
    for row in groups.values():
        row["reminder"] = matching_reminder(row.pop("_reminders"), follow_up, owner)
        if not reminder_matches(row["reminder"], follow_up, owner):
            continue
        for field in QUANTITY_FIELDS:
            row[field] = [
                {"unit": unit, "quantity": format(value.normalize(), "f") if isinstance(value, Decimal) else value}
                for unit, value in sorted(row[field].items())
            ]
        row["unit_prices"] = [
            {"amount": format(amount.normalize(), "f"), "unit": unit}
            for amount, unit in sorted(row["unit_prices"])
        ]
        for field in ("planned_dispatch_dates", "dispatch_dates", "expected_return_dates"):
            row[field] = sorted(row[field])
        selected.append(row)
    selected.sort(key=lambda row: (
        row["task_number"], row["product_name"], row["color"], row["process"], row["factory_name"], row["part_name"], row["id"],
    ), reverse=True)
    return sorted(selected, key=lambda row: reminder_order(row["reminder"]))


def attach_tracking_details(request, rows):
    if not rows:
        return
    schedule_ids = {pk for row in rows for pk in row["schedule_product_ids"] if pk}
    images = {
        product.pk: product_display(product)["image_url"]
        for product in visible_products(request, VIEW_PERMISSION, category="all").filter(pk__in=schedule_ids)
    }
    print_ids = {pk for row in rows if row["process"] == "SCREEN_PRINTING" for pk in row["product_ids"]}
    print_images = {
        product.pk: product_display(None, printing=True, product_line=product)["image_url"]
        for product in printing_product_lines(request).filter(pk__in=print_ids)
    }
    phones = {}
    if has_permission(request, "outsourcing.view_outsourcingfactory"):
        phones = dict(OutsourcingFactory.objects.filter(pk__in={row["factory_id"] for row in rows})
                      .values_list("pk", "contact_phone"))
    for row in rows:
        image = next((images[pk] for pk in row["schedule_product_ids"] if images.get(pk)), "")
        row["product_image_url"] = image or next((print_images[pk] for pk in row["product_ids"] if print_images.get(pk)), "")
        row["factory_phone"] = phones.get(row["factory_id"], "")
