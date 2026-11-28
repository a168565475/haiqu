"""Product-scoped progress from existing workshop and warehouse documents."""
from collections import Counter, defaultdict
from datetime import date

from django.db.models import F, OuterRef, Q, Subquery
from django.db.models.functions import Coalesce, TruncDate
from django.utils import timezone

from apps.access_control import module_policy
from apps.access_control.resource_scopes import has_legacy_permission
from apps.access_control.role_policy import filter_task_scope, role_scopes
from apps.access_control.workshop_scopes import filter_task_products
from apps.boms.models import Bom
from apps.boms.selectors import accessible_boms
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.inventory.models import FinishedGoodsReceipt, FinishedGoodsReceiptStatus
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.workshop_reporting.models import WorkReportLine, WorkshopPlanExecution, WorkshopPlanStatus

from .models import ProductionTaskProduct
from .selectors import legacy_accessible_production_tasks

PLAN_PERMISSION = "production_scheduling.view_productionschedule"
BOM_PERMISSION = "boms.view_bom"

STAGES = (
    "steel_purchase", "metal_issue", "metal_completion",
    "coating_dispatch", "coating_receipt",
    "fabric_purchase", "fabric_arrival", "sewn_receipt",
    "plastic_purchase", "plastic_receipt", "hardware_purchase", "hardware_receipt",
    "packaging_purchase", "packaging_receipt",
    "assembly_first", "assembly_completion", "finished_receipt",
)
FIRST_DATES = {
    "steel_purchase", "fabric_purchase", "plastic_purchase", "hardware_purchase", "packaging_purchase",
    "metal_issue", "assembly_first",
}


def visible_products(request):
    products = ProductionTaskProduct.objects.filter(production_task__archived_at__isnull=True)
    scopes = role_scopes(request, PLAN_PERMISSION)
    if (request.user.is_superuser or scopes & {"MODULE", "ALL"}
            or request.user.has_perm("production_scheduling.view_all_productionschedule")):
        return products
    allowed = Q(pk__in=filter_task_scope(request, products, PLAN_PERMISSION).values("pk"))
    if "WORKSHOP" in scopes:
        allowed |= Q(pk__in=filter_task_products(products, request, PLAN_PERMISSION).values("pk"))
    if not module_policy.enabled() or has_legacy_permission(request, PLAN_PERMISSION):
        allowed |= Q(production_task__in=legacy_accessible_production_tasks(request))
    return products.filter(allowed)


def readable_boms(request):
    if not module_policy.has_permission(request, BOM_PERMISSION):
        return Bom.objects.none()
    return accessible_boms(request, permission=BOM_PERMISSION)


def latest_boms(product_ids):
    return Bom.objects.filter(
        product_line_id__in=product_ids, archived_at__isnull=True,
        production_task_id=F("product_line__production_task_id"),
    ).order_by("product_line_id", "-version_number", "-pk").distinct("product_line_id")


def bom_source_files(queryset):
    return queryset.filter(source_file__archived_at__isnull=True,
                           source_file__scan_status__in=USABLE_FILE_SCAN_STATUSES)


def quantity_text(value):
    if value is None:
        return None
    text = format(value, "f") if not isinstance(value, int) else str(value)
    return text.rstrip("0").rstrip(".") if "." in text else text


def add_batch(batches, kind, day, number, *, party="", material="", quantity=None, unit="", note=""):
    batches.append({
        "kind": kind, "date": day, "number": number, "party": party, "material": material,
        "quantity": quantity_text(quantity), "unit": unit, "note": note,
    })


def assembly_and_finished(ids, batches):
    assembly = ProductionScheduleProductCraft.objects.filter(
        plan_category="ASSEMBLY", craft_type_snapshot="INTERNAL",
        schedule_product__product_line_id__in=ids,
        schedule_product__schedule__production_task_id=F("schedule_product__product_line__production_task_id"),
    )
    report_lines = WorkReportLine.objects.filter(
        report__product_line_id=F("report__schedule_product__product_line_id"),
        report__product_line_id__in=ids,
        report__schedule_product__crafts__in=assembly,
        report__schedule_product__crafts__craft_id=F("report__scheme__scope_craft_id"),
    ).order_by("report__production_date", "report_id", "line_number")
    first_dates, first_lines = {}, defaultdict(set)
    for product, day, number, line, operation, quantity, unit in report_lines.values_list(
        "report__product_line_id", "report__production_date", "report__report_number", "production_line",
        "operation_name_snapshot", "quantity", "unit_name_snapshot",
    ):
        if day == first_dates.setdefault(product, day) and line is not None:
            first_lines[product].add(line)
        add_batch(batches[product], "assembly_first", day, number, party=f"{line} 号线" if line else "",
                  material=operation, quantity=quantity, unit=unit)

    execution = WorkshopPlanExecution.objects.filter(
        schedule_product_id=OuterRef("schedule_product_id"), craft_id=OuterRef("craft_id"),
        status=WorkshopPlanStatus.COMPLETED, completed_at__isnull=False,
    ).values("completed_at")[:1]
    active_plans = assembly.filter(removed_at__isnull=True, schedule_product__removed_at__isnull=True,
                                   schedule_product__schedule__record_status="ACTIVE")
    completion_dates = defaultdict(list)
    for product, day, number, craft in active_plans.annotate(
        finished_at=Subquery(execution),
    ).values_list("schedule_product__product_line_id", "finished_at", "schedule_product__schedule__schedule_number", "craft_name_snapshot"):
        completion_dates[product].append(timezone.localdate(day) if day else None)
        if day:
            add_batch(batches[product], "assembly_completion", timezone.localdate(day), number, material=craft)
    completion = {key: max(dates) for key, dates in completion_dates.items() if all(dates)}

    totals = defaultdict(Counter)
    receipts = FinishedGoodsReceipt.objects.filter(
        production_task_product_id__in=ids, status=FinishedGoodsReceiptStatus.CONFIRMED,
        source_type="PRODUCTION_ORDER",
    ).annotate(business_date=Coalesce("assembly_source__receipt_date", TruncDate("received_at")))
    for product, day, number, quantity, unit_id, unit in receipts.values_list(
        "production_task_product_id", "business_date", "receipt_number", "received_quantity", "unit_id", "unit__unit_name",
    ):
        totals[product][(unit_id, unit)] += quantity
        add_batch(batches[product], "finished_receipt", day, number, quantity=quantity, unit=unit)
    return first_lines, completion, totals


def tracking_data(request, products, *, detail=False):
    from .material_tracking_processing import processing_batches
    from .material_tracking_purchases import purchase_batches

    ids = [product.pk for product in products]
    if not ids:
        return []
    boms = {bom.product_line_id: bom for bom in latest_boms(ids).select_related("source_file")}
    visible_bom_ids = set(readable_boms(request).filter(pk__in=[bom.pk for bom in boms.values()]).values_list("pk", flat=True))
    batches = defaultdict(list)
    fabrics = purchase_batches(products, boms, batches)
    processing_batches(ids, batches)
    first_lines, completion_dates, totals = assembly_and_finished(ids, batches)

    rows = []
    for product in products:
        events = sorted(batches[product.pk], key=lambda event: (event["date"] or date.min, event["number"]))
        stages = {name: {"date": None, "batch_count": 0, "note": ""} for name in STAGES}
        for event in events:
            name = event["kind"]
            stage = stages[name]
            stage["batch_count"] += 1
            if event["date"] and (stage["date"] is None or name not in FIRST_DATES):
                stage["date"] = event["date"]
            if event["note"] in ("共采待分配", "未见已发布采购日期"):
                stage["note"] = event["note"]
        fabric_rows, fabric_date, fabric_note = fabrics[product.pk]
        stages["fabric_arrival"].update(date=fabric_date, note=fabric_note)
        stages["assembly_completion"]["date"] = completion_dates.get(product.pk)
        factories = sorted({event["party"] for event in events if event["party"]
                            and event["kind"] in ("coating_dispatch", "coating_receipt")})
        bom = boms.get(product.pk)
        bom_link = None
        if bom and bom.pk in visible_bom_ids:
            source = bom.source_file
            file_name = source.original_name if (
                source and not source.archived_at and source.scan_status in USABLE_FILE_SCAN_STATUSES
            ) else ""
            bom_link = {"id": bom.pk, "file_name": file_name}
        if detail:
            rows.append({"batches": events, "fabrics": fabric_rows, "packaging_requirements": product.packaging_method})
        else:
            rows.append({
                "id": product.pk, "task_number": product.production_task.task_number,
                "product_name": product.product_name_snapshot, "order_quantity": str(product.quantity),
                "order_unit": product.unit.unit_name if product.unit_id else "",
                "color": product.color_name_snapshot or product.customer_color_snapshot or product.color_code_snapshot,
                "stages": stages, "coating_factories": factories, "assembly_lines": sorted(first_lines[product.pk]),
                "finished_quantities": [{"unit": unit, "quantity": str(quantity)}
                                        for (_, unit), quantity in totals[product.pk].items()],
                "bom": bom_link, "has_packaging_requirements": bool(product.packaging_method.strip()),
            })
    return rows
