"""Read-only daily workshop summaries, with each source scoped independently."""
from django.db.models import Case, CharField, Exists, F, Max, OuterRef, Q, Sum, When
from django.db.models.functions import Cast, Coalesce

from apps.access_control.module_policy import has_permission
from apps.access_control.resource_scopes import has_legacy_permission, resource_ids
from apps.access_control.role_policy import filter_task_scope
from apps.boms.material_flow_calculations import MaterialFlowValueError, pipe_plan_for_line
from apps.boms.models import BomLine, BomStatus
from apps.inventory.models import FinishedGoodsReceipt, FinishedGoodsReceiptSource, FinishedGoodsReceiptStatus
from apps.inventory.receipt_permissions import receipt_record_workshops
from apps.inventory.selectors import scoped_finished_receipts, scoped_inventory_records
from apps.material_issues.models import MetalProcessingCompletion
from apps.material_issues.processing_selectors import readable_processing_lines
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.production_scheduling.selectors import schedule_items_for_category
from apps.production_tasks.material_tracking import latest_boms
from apps.production_tasks.selectors import legacy_accessible_production_tasks

from .models import WorkReportLine
from .selectors import work_report_selection_sources, work_report_task_products, work_reports_in_plan_category


METAL_PERMISSION = "material_issues.view_metalprocessingsource"
PLAN_PERMISSION = "production_scheduling.view_productionschedule"
REPORT_PERMISSION = "workshop_reporting.view_workreport"
RECEIPT_PERMISSION = "inventory.view_finishedgoodsreceipt"


def planned_metal_products(request, task_number):
    plans = ProductionScheduleProduct.objects.none()
    if has_permission(request, PLAN_PERMISSION):
        plans = schedule_items_for_category(request, "METAL").filter(
            schedule__production_task__task_number__icontains=task_number,
            schedule__production_task_id=F("product_line__production_task_id"),
        )
        if resource_ids(request, METAL_PERMISSION, "CRAFT", include_legacy=False) is not None:
            allowed = filter_task_scope(request, plans, METAL_PERMISSION, "schedule__production_task")
            if has_legacy_permission(request, METAL_PERMISSION):
                legacy = plans if request.user.has_perm("material_issues.view_all_materialissue") else plans.filter(
                    schedule__production_task__in=legacy_accessible_production_tasks(request),
                )
                allowed = allowed | legacy
            plans = allowed
    return plans.order_by().values("product_line_id")


def pipe_row(product, identity, part_name, specification, length, demand):
    dimensions = " × ".join(filter(None, (specification.removesuffix("mm").strip(), str(length or ""))))
    return {
        "id": f"{product.pk}:{identity}", "task_number": product.production_task.task_number,
        "product_name": product.product_name_snapshot, "part_name": part_name, "specification": dimensions,
        "order_quantity": demand, "unit": "支",
    }


def metal_rows(request, day, task_number):
    sources = readable_processing_lines(request).filter(
        issue__production_task__task_number__icontains=task_number,
        issue__product_line__production_task_id=F("issue__production_task_id"),
        requirement__product_line_id=F("issue__product_line_id"), requirement__component_identity__isnull=False,
    ).prefetch_related(None)
    completions = MetalProcessingCompletion.objects.filter(
        source__issue_line_id__in=sources.order_by().values("pk"), completion_date__lte=day,
    ).order_by().values("source__issue_line__issue__product_line_id", "source__issue_line__requirement__component_identity")
    totals = {
        (row["source__issue_line__issue__product_line_id"], row["source__issue_line__requirement__component_identity"]): row
        for row in completions.annotate(today=Sum("good_pieces", filter=Q(completion_date=day)), cumulative=Sum("good_pieces"))
    }
    rows = {}
    bom_ids = latest_boms(planned_metal_products(request, task_number)).values("pk")
    planned = BomLine.objects.filter(
        section__bom_id__in=bom_ids, section__bom__status=BomStatus.VERIFIED,
        section__bom__order_quantity=F("section__bom__product_line__quantity"), cutting_length_mm__isnull=False,
    ).select_related("section__bom__product_line__production_task").order_by("section__bom_id", "section_id", "line_number")
    for line in planned:
        product = line.section.bom.product_line
        try:
            demand = pipe_plan_for_line(line)["demand_pieces"]
        except MaterialFlowValueError:
            demand = None
        rows[product.pk, line.component_identity] = pipe_row(
            product, line.component_identity, line.part_name, line.specification, line.cutting_length_mm, demand,
        )
    for line in sources:
        product, identity = line.issue.product_line, line.requirement.component_identity
        if (product.pk, identity) in rows:
            continue
        frozen = line.conversion_snapshot
        specification = next((field["value"] for field in frozen.get("bom_attributes", [])
                              if field["key"] == "specification"), line.specification_snapshot)
        rows[product.pk, identity] = pipe_row(
            product, identity, frozen.get("part_name") or line.material_name_snapshot,
            specification, frozen.get("cutting_length_mm"), frozen.get("demand_pieces"),
        )
    for key, row in rows.items():
        total = totals.get(key, {})
        demand, cumulative = row["order_quantity"], total.get("cumulative", 0)
        row.update(today=total.get("today") or 0, cumulative=cumulative,
                   remaining=int(demand) - cumulative if demand is not None else None)
    return sorted(rows.values(), key=lambda row: (row["task_number"], row["product_name"], row["part_name"], row["id"]))


def category_sources(request, category, task_number):
    reports, crafts = work_report_selection_sources(request)
    reports = work_reports_in_plan_category(reports, category).filter(
        product_line__production_task__task_number__icontains=task_number,
        product_line_id=F("schedule_product__product_line_id"),
        product_line__production_task_id=F("schedule_product__schedule__production_task_id"),
    )
    crafts = crafts.filter(
        plan_category=category, schedule_product__schedule__production_task__task_number__icontains=task_number,
        schedule_product__schedule__production_task_id=F("schedule_product__product_line__production_task_id"),
    )
    return reports, crafts


def sewing_detail_rows(request, day, task_number):
    reports, _ = category_sources(request, "SEWING", task_number)
    return WorkReportLine.objects.filter(report__in=reports.filter(production_date=day).order_by()).order_by().annotate(
        task_number=F("report__product_line__production_task__task_number"),
        product_name=F("report__product_line__product_name_snapshot"),
        color=F("report__product_line__color_name_snapshot"), unit=F("unit_name_snapshot"),
        employee_key=Coalesce("workshop_employee_id", "legacy_employee_id"),
        unlinked_employee_name=Case(When(employee_key__isnull=True, then=F("employee_name_snapshot")), default=None),
    ).values(
        "report__product_line_id", "task_number", "product_name", "color", "employee_key", "unlinked_employee_name",
        "work_item__operation_id", "unit",
    ).annotate(
        id=Max(Cast("pk", CharField())), employee=Max("employee_name_snapshot"),
        operation=Max("operation_name_snapshot"), today=Sum("quantity"),
    ).order_by("task_number", "report__product_line_id", "employee", "operation", "unit", "id")


def category_orders(request, category, day, task_number):
    reports, crafts = category_sources(request, category, task_number)
    return work_report_task_products(reports.filter(production_date__lte=day), crafts).order_by(
        "production_task__task_number", "line_number", "pk",
    )


def order_values(products):
    return products.values(
        "id", task_number=F("production_task__task_number"), product_name=F("product_name_snapshot"),
        color=F("color_name_snapshot"), order_quantity=F("quantity"), order_unit=F("unit__unit_name"),
    )


def sewing_order_rows(request, day, task_number):
    return order_values(category_orders(request, "SEWING", day, task_number))


def receipt_visible_products(request, products):
    plans = ProductionScheduleProduct.objects.filter(product_line_id__in=products.order_by().values("pk"))
    links = ProductionScheduleProductCraft.objects.filter(
        schedule_product_id=OuterRef("pk"), plan_category="ASSEMBLY", craft_type_snapshot="INTERNAL",
    )
    workshops = receipt_record_workshops(request, RECEIPT_PERMISSION)
    if workshops is not None:
        plans = plans.filter(Exists(links.filter(craft__workshop_id__in=workshops)),
                             ~Exists(links.exclude(craft__workshop_id__in=workshops)))
    else:
        plans = scoped_inventory_records(plans.filter(Exists(links)), request, RECEIPT_PERMISSION,
                                         task_lookup="schedule__production_task", workshop_lookup="crafts__craft__workshop_id")
    return set(plans.order_by().values_list("product_line_id", flat=True))


def assembly_rows(request, day, task_number):
    products = category_orders(request, "ASSEMBLY", day, task_number)
    totals = {}
    visible_products = set()
    if has_permission(request, RECEIPT_PERMISSION):
        visible_products = receipt_visible_products(request, products)
        # A confirmed receipt is the same submission; the warehouse date never moves the daily total.
        records = FinishedGoodsReceipt.objects.filter(
            production_task_product_id__in=products.order_by().values("pk"),
            assembly_source__schedule_product__product_line_id=F("production_task_product_id"),
            assembly_source__schedule_product__schedule__production_task_id=F("production_task_product__production_task_id"),
            source_type=FinishedGoodsReceiptSource.PRODUCTION_ORDER, status__in=FinishedGoodsReceiptStatus.values,
            unit_id=F("production_task_product__unit_id"), submitted_at__date__lte=day,
        )
        visible = scoped_finished_receipts(records, request).order_by().values("pk")
        totals = {row["production_task_product_id"]: row for row in FinishedGoodsReceipt.objects.filter(
            pk__in=visible,
        ).order_by().values("production_task_product_id").annotate(
            today=Sum("received_quantity", filter=Q(submitted_at__date=day)), cumulative=Sum("received_quantity"),
        )}
    rows = list(order_values(products))
    for row in rows:
        total = totals.get(row["id"], {})
        if total or row["id"] in visible_products:
            cumulative = total.get("cumulative", 0)
            row.update(today=total.get("today") or 0, cumulative=cumulative, remaining=row["order_quantity"] - cumulative)
    return rows
