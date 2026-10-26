"""排产列表的阶段展示统计；不参与订单完成、报工或库存状态变更。"""

from collections import defaultdict
from decimal import Decimal, localcontext

from django.db.models import Count, Q, Sum

from apps.inventory.models import FinishedGoodsOutboundLine, FinishedGoodsReceipt
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProductCraft
from apps.production_scheduling.selectors import schedules_with_context

from .models import WageScheme, WorkReportLine
from .schedule_outsourcing_status import schedule_outsourcing_statuses


STAGE_DATES = {
    "METAL": "metal_return_date",
    "CUTTING": "sewing_return_date",
    "SEWING": "sewing_return_date",
    "ASSEMBLY": "finished_inbound_date",
}


def _metric(status="NOT_CONFIGURED", required=0, completed=0):
    return {"status": status, "required": Decimal(required), "completed": Decimal(completed)}


def _percentage(metric):
    if metric["status"] != "READY":
        return None
    if metric["required"] <= 0:
        return 0
    if metric["completed"] >= metric["required"]:
        return 100
    # 真正完成前不因四舍五入显示 100%。
    with localcontext() as context:
        context.prec = 60
        return max(0, min(99, int(metric["completed"] * 100 / metric["required"])))


def _aggregate(metrics):
    if not metrics or all(item["status"] == "NOT_APPLICABLE" for item in metrics):
        return _metric("NOT_APPLICABLE")
    if any(item["status"] != "READY" for item in metrics):
        return _metric()
    # 未填写报工基数时按 0% 展示，不能用部分已填写的分母显示整单完成。
    if any(item["required"] <= 0 for item in metrics):
        return _metric("READY")
    return _metric(
        "READY", sum(item["required"] for item in metrics),
        sum(item["completed"] for item in metrics),
    )


def _internal_reporting_metrics(products, full_links, as_of_date):
    categories = ("METAL", "CUTTING", "SEWING")
    scopes_by_category = {}
    scope_keys_by_category = {}
    scheme_scopes = Q(pk__in=[])
    for category in categories:
        scopes_by_product = {}
        scope_keys = set()
        for product in products:
            links = [link for link in full_links[product.pk]
                     if link.craft_type_snapshot == "INTERNAL" and link.plan_category == category]
            visible_ids = {link.pk for link in product.active_crafts}
            scopes = {(product.product_line_id, link.craft.workshop_id, link.craft_id) for link in links}
            visible = all(link.pk in visible_ids for link in links)
            scopes_by_product[product.pk] = (scopes, visible)
            if visible:
                scope_keys.update(scopes)
        scopes_by_category[category] = scopes_by_product
        scope_keys_by_category[category] = scope_keys
        # 合并原三类查询条件，不把不同类别的产品、车间、工艺重新交叉组合。
        scheme_scopes |= Q(
            product_line_id__in={key[0] for key in scope_keys},
            workshop_id__in={key[1] for key in scope_keys},
            scope_craft_id__in={key[2] for key in scope_keys},
        )
    schemes_by_scope = defaultdict(list)
    schemes = list(WageScheme.objects.filter(
        scheme_scopes,
        status="APPROVED", effective_from__lte=as_of_date,
    ).filter(Q(effective_to__isnull=True) | Q(effective_to__gte=as_of_date)).prefetch_related("lines"))
    for scheme in schemes:
        schemes_by_scope[(scheme.product_line_id, scheme.workshop_id, scheme.scope_craft_id)].append(scheme)
    report_scopes = Q(pk__in=[])
    for category, scope_keys in scope_keys_by_category.items():
        work_item_ids = set()
        for scope in scope_keys:
            for scheme in schemes_by_scope[scope]:
                work_item_ids.update(line.work_item_id for line in scheme.lines.all() if line.status == "ACTIVE")
        report_scopes |= Q(
            report__scheme__scope_craft__plan_category=category, work_item_id__in=work_item_ids,
        )
    quantities_by_category = defaultdict(dict)
    # scope 沿用排产快照；报工仍按方案工艺的当前分类汇总，避免同工项跨阶段串量。
    for row in WorkReportLine.objects.filter(
        report_scopes,
        report__schedule_product_id__in=[product.pk for product in products],
        report__production_date__lte=as_of_date,
        report__scheme__scope_craft__craft_type="INTERNAL",
    ).values("report__schedule_product_id", "work_item_id", "report__scheme__scope_craft__plan_category").annotate(quantity=Sum("quantity")):
        category = row["report__scheme__scope_craft__plan_category"]
        quantities_by_category[category][(row["report__schedule_product_id"], row["work_item_id"])] = row["quantity"]
    return {
        category: _category_reporting_metrics(products, scopes_by_category[category], schemes_by_scope, quantities_by_category[category])
        for category in categories
    }


def _category_reporting_metrics(products, scopes_by_product, schemes_by_scope, quantities):
    result = {}
    for product in products:
        scopes, visible = scopes_by_product[product.pk]
        metrics = []
        if not scopes:
            result[product.pk] = _metric("NOT_APPLICABLE")
            continue
        if not visible:
            result[product.pk] = _metric()
            continue
        for scope in scopes:
            candidates = schemes_by_scope[scope]
            if len(candidates) > 1:
                metrics.append(_metric())
                continue
            lines = [line for line in candidates[0].lines.all() if line.status == "ACTIVE"] if len(candidates) == 1 else []
            if any(line.order_quantity_snapshot != product.product_line.quantity for line in lines):
                metrics.append(_metric())
                continue
            if not lines or any(
                line.required_quantity_snapshot is None or line.required_quantity_snapshot <= 0
                for line in lines
            ):
                # 列表厂内工序只看报工；尚未填写方案或需要报工数量时按 0%。
                metrics.append(_metric("READY"))
                continue
            # 每道报工明细分别封顶，不能用一个部位超报抵掉其他部位的欠量。
            metrics.extend(_metric(
                "READY", line.required_quantity_snapshot,
                min(line.required_quantity_snapshot, quantities.get((product.pk, line.work_item_id), 0)),
            ) for line in lines)
        result[product.pk] = _aggregate(metrics)
    return result


def _outbound_progress(schedule, finished, shipped):
    products = []
    for product in schedule.active_products:
        known = (shipped is not None and product.planned_quantity == product.product_line.quantity
                 and product.source_quantity_snapshot == product.product_line.quantity)
        received = finished.get(product.product_line_id, 0)
        outbound = shipped.get(product.product_line_id, 0) if shipped is not None else 0
        required = product.product_line.quantity
        metric = _metric("READY", required, min(required, outbound)) if known else _metric()
        products.append({
            "schedule_product_id": str(product.pk), "status": metric["status"],
            "percentage": _percentage(metric), "planned_date": None,
            "received_quantity": received if known else None,
            "order_quantity": required if known else None,
            "outbound_quantity": outbound if known else None,
        })
    known = (bool(products) and len(products) == schedule.stage_product_count
             and all(product["status"] == "READY" for product in products))
    # 以订单数量衡量交付；每个产品分别封顶，避免超出库抵掉另一产品尚未出库的数量。
    metric = _metric("READY", sum(item["order_quantity"] for item in products),
                     sum(min(item["order_quantity"], item["outbound_quantity"]) for item in products)) if known else _metric()
    return {"status": metric["status"], "percentage": _percentage(metric), "products": products}


def schedule_stage_progress_statuses(schedule_ids, *, request, as_of_date):
    """仅接收端点已校验可见的排产 ID，继续沿用列表的产品和工艺权限过滤。"""
    output = {
        str(schedule_id): {
            "as_of_date": as_of_date.isoformat(), "overall_percentage": None,
            "stage_progress": {
                stage: {"status": "NOT_CONFIGURED", "percentage": None, "products": []}
                for stage in STAGE_DATES
            },
        } for schedule_id in schedule_ids
    }
    schedules = list(schedules_with_context(
        ProductionSchedule.objects.filter(pk__in=schedule_ids, record_status="ACTIVE").annotate(
            stage_product_count=Count("products", filter=Q(products__removed_at__isnull=True), distinct=True),
        ), request=request,
    ))
    if not schedules:
        return output
    outsourcing = schedule_outsourcing_statuses(schedules, request=request, as_of_date=as_of_date)
    products = [product for schedule in schedules for product in schedule.active_products]
    full_links = defaultdict(list)
    for link in ProductionScheduleProductCraft.objects.filter(
        schedule_product_id__in=[product.pk for product in products], removed_at__isnull=True,
    ).select_related("craft"):
        full_links[link.schedule_product_id].append(link)
    reporting = _internal_reporting_metrics(products, full_links, as_of_date)
    finished = dict(FinishedGoodsReceipt.objects.filter(
        production_task_product_id__in=[product.product_line_id for product in products],
        source_type="PRODUCTION_ORDER", status="CONFIRMED", received_at__date__lte=as_of_date,
    ).values("production_task_product_id").annotate(quantity=Sum("received_quantity"))
        .values_list("production_task_product_id", "quantity"))
    shipped = None
    if request.user.has_perm("inventory.view_finishedgoodsoutbound"):
        shipped = dict(FinishedGoodsOutboundLine.objects.filter(
            receipt__production_task_product_id__in=[product.product_line_id for product in products],
            receipt__source_type="PRODUCTION_ORDER", receipt__status="CONFIRMED",
            receipt__received_at__date__lte=as_of_date, outbound__outbound_at__date__lte=as_of_date,
        ).values("receipt__production_task_product_id").annotate(quantity=Sum("outbound_quantity"))
            .values_list("receipt__production_task_product_id", "quantity"))
    for schedule in schedules:
        metrics = {stage: [] for stage in STAGE_DATES}
        stage_products = {stage: [] for stage in STAGE_DATES}
        for product in schedule.active_products:
            links = full_links[product.pk]
            product_metrics = {category: values[product.pk] for category, values in reporting.items()}
            assembly_links = [link for link in links if link.plan_category == "ASSEMBLY"]
            visible_ids = {link.pk for link in product.active_crafts}
            if not assembly_links:
                product_metrics["ASSEMBLY"] = _metric("NOT_APPLICABLE")
            elif any(link.pk not in visible_ids for link in assembly_links):
                product_metrics["ASSEMBLY"] = _metric()
            else:
                required = product.product_line.quantity
                product_metrics["ASSEMBLY"] = _metric(
                    "READY", required, min(required, finished.get(product.product_line_id, 0)),
                )
            # 报工基数和成品入库按任务产品归集，分批排产不能借用全单口径冒充本批完成。
            if (product.planned_quantity != product.product_line.quantity
                    or product.source_quantity_snapshot != product.product_line.quantity):
                product_metrics = {stage: _metric() for stage in STAGE_DATES}
            for stage, metric in product_metrics.items():
                planned_date = getattr(product, STAGE_DATES[stage])
                metrics[stage].append(metric)
                stage_products[stage].append({
                    "schedule_product_id": str(product.pk), "status": metric["status"],
                    "percentage": _percentage(metric),
                    "planned_date": planned_date.isoformat() if planned_date else None,
                })
        stages = {}
        for stage, product_metrics in metrics.items():
            metric = _aggregate(product_metrics)
            # 可见产品只是整单的一部分时，不用局部数量代替整单总进度。
            if len(schedule.active_products) != schedule.stage_product_count:
                metric = _metric()
            stages[stage] = {
                "status": metric["status"], "percentage": _percentage(metric),
                "products": stage_products[stage],
            }
        percentages = [stage["percentage"] for stage in stages.values()]
        output[str(schedule.pk)] = {
            "as_of_date": as_of_date.isoformat(), "stage_progress": stages,
            "outsourcing_status": outsourcing[str(schedule.pk)],
            "outbound_progress": _outbound_progress(schedule, finished, shipped),
            "overall_percentage": sum(percentages) // 4 if all(value is not None for value in percentages) else None,
        }
    return output
