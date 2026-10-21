from decimal import Decimal, ROUND_HALF_UP

from django.db.models import Prefetch, Sum
from django.utils import timezone

from apps.inventory.assembly_receipts import assembly_progress_for_plans
from apps.production_scheduling.models import ProductionScheduleProduct, ProductionScheduleProductCraft
from apps.workshop_config.models import PlanCategory

from .models import WageScheme, WageSchemeLineStatus, WageSchemeStatus, WorkReportLine
from .services import wage_scheme_progress


def schedule_progress_statuses(schedule_ids, production_date=None):
    """计算已通过访问范围校验的排产计划进度，保留输入顺序。"""
    schedule_ids = list(schedule_ids)
    production_date = production_date or timezone.localdate()
    products = list(
        ProductionScheduleProduct.objects.filter(
            schedule_id__in=schedule_ids, removed_at__isnull=True,
        ).select_related("product_line").prefetch_related(
            Prefetch(
                "crafts",
                queryset=ProductionScheduleProductCraft.objects.filter(
                    removed_at__isnull=True,
                    craft_type_snapshot="INTERNAL",
                ).select_related("craft"),
                to_attr="active_internal_crafts",
            )
        )
    )
    scope_keys = {
        (product.product_line_id, link.craft.workshop_id, link.craft_id)
        for product in products
        for link in product.active_internal_crafts
        if link.plan_category in {PlanCategory.METAL, PlanCategory.CUTTING, PlanCategory.SEWING}
    }
    schemes = list(
        WageScheme.objects.filter(
            product_line_id__in=[key[0] for key in scope_keys],
            workshop_id__in=[key[1] for key in scope_keys],
            scope_craft_id__in=[key[2] for key in scope_keys],
            status=WageSchemeStatus.APPROVED,
            effective_from__lte=production_date,
        ).filter(
            effective_to__isnull=True,
        ).prefetch_related("lines")
    )
    # 同一天结束的版本仍然有效，因此把有截止日期的适用版本补入。
    schemes.extend(
        WageScheme.objects.filter(
            product_line_id__in=[key[0] for key in scope_keys],
            workshop_id__in=[key[1] for key in scope_keys],
            scope_craft_id__in=[key[2] for key in scope_keys],
            status=WageSchemeStatus.APPROVED,
            effective_from__lte=production_date,
            effective_to__gte=production_date,
        ).prefetch_related("lines")
    )
    schemes_by_scope = {}
    for scheme in schemes:
        schemes_by_scope.setdefault(
            (scheme.product_line_id, scheme.workshop_id, scheme.scope_craft_id), []
        ).append(scheme)
    work_item_ids = {
        line.work_item_id
        for scheme in schemes
        for line in scheme.lines.all()
        if line.status == WageSchemeLineStatus.ACTIVE
    }
    cumulative_by_product = {}
    for row in WorkReportLine.objects.filter(
        report__schedule_product_id__in=[product.pk for product in products],
        work_item_id__in=work_item_ids,
    ).values("report__schedule_product_id", "work_item_id").annotate(quantity=Sum("quantity")):
        cumulative_by_product.setdefault(row["report__schedule_product_id"], {})[
            row["work_item_id"]
        ] = row["quantity"]

    products_by_schedule = {}
    for product in products:
        products_by_schedule.setdefault(product.schedule_id, []).append(product)

    category_groups = {
        "METAL": {PlanCategory.METAL},
        "SEWING": {PlanCategory.CUTTING, PlanCategory.SEWING},
    }
    finished_by_product = assembly_progress_for_plans(products)
    response_rows = []
    for schedule_id in schedule_ids:
        schedule_products = products_by_schedule.get(schedule_id, [])
        progress = {
            "MATERIAL": {"status": "READY", "percentage": 100, "display": "100%"},
        }
        # 成品入库按入库原单统计，与装配报工进度、当前库存余量无关。
        finished_metrics = [finished_by_product[str(product.pk)] for product in schedule_products]
        required = sum(item["required"] for item in finished_metrics)
        received = sum(item["received"] for item in finished_metrics)
        finished_percentage = 0 if required <= 0 else int(
            min(Decimal("100"), Decimal(received) * 100 / required).quantize(
                Decimal("1"), rounding=ROUND_HALF_UP,
            )
        )
        progress["ASSEMBLY"] = {
            "status": "READY", "percentage": finished_percentage, "display": f"{finished_percentage}%",
        }
        for output_key, categories in category_groups.items():
            applicable_product_scopes = set()
            for product in schedule_products:
                for link in product.active_internal_crafts:
                    if link.plan_category in categories:
                        applicable_product_scopes.add(
                            (
                                product.pk,
                                (product.product_line_id, link.craft.workshop_id, link.craft_id),
                            )
                        )
            if not applicable_product_scopes:
                progress[output_key] = {"status": "NOT_APPLICABLE", "percentage": None, "display": "—"}
                continue
            metrics = []
            is_configured = True
            for product_id, scope in applicable_product_scopes:
                candidates = schemes_by_scope.get(scope, [])
                if len(candidates) != 1:
                    is_configured = False
                    break
                metrics.append(
                    wage_scheme_progress(candidates[0], cumulative_by_product.get(product_id, {}))
                )
            if not is_configured or any(metric is None for metric in metrics):
                progress[output_key] = {
                    "status": "NOT_CONFIGURED", "percentage": None, "display": "待设置工价",
                }
                continue
            required_total = sum((metric["required_total"] for metric in metrics), 0)
            reported_total = sum((metric["reported_total"] for metric in metrics), 0)
            percentage = 0 if required_total <= 0 else int(
                min(Decimal("100"), (reported_total * Decimal("100") / required_total)).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP,
                )
            )
            progress[output_key] = {
                "status": "READY", "percentage": max(0, percentage), "display": f"{max(0, percentage)}%",
            }
        response_rows.append({"schedule_id": str(schedule_id), "progress": progress})
    return response_rows
