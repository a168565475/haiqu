"""车间主管工作台。每项计划是一条排产产品工艺，车间、报工与入库分别取授权交集。"""

from collections import defaultdict
from datetime import timedelta

from django.db.models import Case, CharField, Count, Exists, F, OuterRef, Q, Subquery, Sum, Value, When
from django.db.models.functions import Coalesce, TruncDate
from rest_framework.exceptions import PermissionDenied

from apps.access_control.module_policy import has_permission
from apps.access_control.models import RoleGrantResource
from apps.access_control.production_role_templates import DIRECTORS
from apps.access_control.resource_scopes import configured, enforcing, resource_ids
from apps.access_control.sales_policy import access_for
from apps.inventory.api.finished_receipts import record_queryset
from apps.inventory.models import FinishedGoodsReceipt
from apps.production_scheduling.models import ProductionScheduleProductCraft
from apps.production_scheduling.selectors import accessible_production_schedules
from apps.workshop_reporting.models import WageSchemeLine, WorkReportLine, WorkshopPlanExecution
from apps.workshop_reporting.selectors import accessible_wage_schemes, accessible_work_reports, allowed_workshop_ids

from .dashboard import CATEGORY_GROUPS, REPORT_PERMISSION, decimal_string


SCHEDULE_PERMISSION = "production_scheduling.view_productionschedule"
RECEIPT_PERMISSION = "inventory.view_finishedgoodsreceipt"
SCHEME_PERMISSION = "workshop_reporting.view_wagescheme"
DUE_FIELDS = {"METAL": "metal_return_date", "SEWING": "sewing_return_date", "ASSEMBLY": "finished_inbound_date"}
TASK = "schedule_product__schedule__production_task"
OPEN_STAGES = ("working", "planned", "unknown")
REPORT_ORDER = ("-report__production_date", "-report__created_at", "-report_id", "line_number", "id")
REPORT_CONTEXT = "report__product_line__production_task"
RECEIPT_CONTEXT = "production_task_product__production_task"


def director_scopes(request):
    access = access_for(request)
    roles = {role["id"]: role["code"].removesuffix("_DIRECTOR") for role in access["roles"] if role["code"] in DIRECTORS}
    scopes = defaultdict(set)
    if access["is_superuser"] and not roles:
        return dict.fromkeys(("ASSEMBLY", "METAL", "SEWING"))
    if roles and configured():
        resources = RoleGrantResource.objects.filter(
            grant__role_id__in=roles, grant__scope="WORKSHOP", workshop__isnull=False,
            grant__permission__content_type__app_label="production_scheduling", grant__permission__codename="view_productionschedule",
        ).values_list("grant__role_id", "workshop_id")
        for role_id, workshop_id in resources:
            scopes[roles[str(role_id)]].add(str(workshop_id))
    return {key: scopes[key] for key in CATEGORY_GROUPS if key in scopes}


def quantity(target=None, done=None, unit="", reason=""):
    remaining = max(target - done, 0) if target is not None and done is not None else None
    def fmt(value):
        return decimal_string(value) if value is not None else None
    return {"target": fmt(target), "done": fmt(done), "remaining": fmt(remaining), "unit": unit, "reason": reason}


def page_of(rows, params):
    total = rows.count()
    page, size = params["page"], params["page_size"]
    start = (page - 1) * size
    return rows[start:start + size], {"page": page, "page_size": size, "total": total, "total_pages": (total + size - 1) // size}


class DirectorWorkbench:
    def __init__(self, request, workshop, today):
        scopes = director_scopes(request)
        if not scopes or not has_permission(request, SCHEDULE_PERMISSION):
            raise PermissionDenied("当前岗位没有车间主管工作台查看权限。")
        self.workshops = list(scopes)
        self.workshop = workshop or self.workshops[0]
        if self.workshop not in scopes:
            raise PermissionDenied("当前岗位无权查看该车间。")
        self.request = request
        self.today = today
        shop_ids = scopes[self.workshop]
        self.history_links = ProductionScheduleProductCraft.objects.filter(
            craft_type_snapshot="INTERNAL", plan_category__in=CATEGORY_GROUPS[self.workshop],
            schedule_product__schedule__in=accessible_production_schedules(request).order_by().values("pk"),
        )
        if shop_ids is not None:
            self.history_links = self.history_links.filter(craft__workshop_id__in=shop_ids)
        self.links = self.history_links.filter(removed_at__isnull=True, schedule_product__removed_at__isnull=True,
                                              schedule_product__schedule__record_status="ACTIVE")
        report_ids = allowed_workshop_ids(request, for_work_reports=True, permission=REPORT_PERMISSION)
        self.report_shops = None if report_ids is None else {str(pk) for pk in report_ids}
        self.can_report = has_permission(request, REPORT_PERMISSION) and (
            self.report_shops is None or bool(self.report_shops.intersection(shop_ids or self.report_shops)))
        self.can_receipt = self.workshop == "ASSEMBLY" and has_permission(request, RECEIPT_PERMISSION)
        self.receipt_shops = None
        if self.can_receipt and enforcing(request, RECEIPT_PERMISSION):
            self.receipt_shops = resource_ids(request, RECEIPT_PERMISSION, "WORKSHOP")
            if self.receipt_shops is not None:
                self.can_receipt = bool(self.receipt_shops.intersection(shop_ids or self.receipt_shops))
        self.report_lines = WorkReportLine.objects.filter(
            report__in=accessible_work_reports(request, permission=REPORT_PERMISSION).order_by().values("pk"),
            report__production_date__lte=today,
        ) if self.can_report else WorkReportLine.objects.none()
        if self.report_shops is not None:
            self.report_lines = self.report_lines.filter(report__workshop_id__in=self.report_shops)
        # 一张入库单可能通过多条工艺满足来源可见条件。先按主键去重再汇总数量。
        self.receipts = FinishedGoodsReceipt.objects.filter(pk__in=record_queryset(request).order_by().values("pk")).annotate(
            business_date=Coalesce("assembly_source__receipt_date", TruncDate("received_at")),
        ).filter(
            status="CONFIRMED", source_type="PRODUCTION_ORDER", business_date__lte=today,
        ) if self.can_receipt else None

    def plans(self):
        links = self.links.filter(**{f"{TASK}__archived_at__isnull": True, f"{TASK}__status__in":
                                   ("READY", "IN_PRODUCTION", "COMPLETED", "PENDING_VALIDATION")})
        reported = self.report_lines.filter(report__schedule_product_id=OuterRef("schedule_product_id"),
                                           report__workshop_id=OuterRef("craft__workshop_id"),
                                           report__scheme__scope_craft_id=OuterRef("craft_id"))
        finished = WorkshopPlanExecution.objects.filter(schedule_product_id=OuterRef("schedule_product_id"),
                                                        craft_id=OuterRef("craft_id"), status="COMPLETED")
        complete = Q(**{f"{TASK}__status": "COMPLETED"})
        if self.can_report:
            reported_complete = Q(Exists(finished))
            if self.report_shops is not None:
                reported_complete &= Q(craft__workshop_id__in=self.report_shops)
            complete |= reported_complete
        if self.can_receipt:
            receipts = self.receipts.filter(production_task_product_id=OuterRef("schedule_product__product_line_id"))
            total = receipts.filter(unit_id=OuterRef("schedule_product__product_line__unit_id")).order_by().values(
                "production_task_product_id").annotate(n=Sum("received_quantity")).values("n")
            wrong_unit = receipts.exclude(unit_id=OuterRef("schedule_product__product_line__unit_id"))
            links = links.alias(received_total=Subquery(total))
            all_received = Q(received_total__gte=F("schedule_product__product_line__quantity")) & ~Q(Exists(wrong_unit))
            if self.receipt_shops is not None:
                all_received &= Q(craft__workshop_id__in=self.receipt_shops)
            complete |= all_received
        cases = [When(complete, then=Value("completed"))]
        if self.can_report:
            if self.report_shops is not None:
                cases.append(When(~Q(craft__workshop_id__in=self.report_shops), then=Value("unknown")))
            cases.append(When(Exists(reported), then=Value("working")))
        return links.annotate(
            stage=Case(*cases, default=Value("planned" if self.can_report else "unknown"), output_field=CharField()),
            due_date=F("schedule_product__" + DUE_FIELDS[self.workshop]),
        ).order_by("due_date", f"{TASK}__task_number", "schedule_product__line_number", "craft_name_snapshot", "pk")

    def select_items(self, key, date=None):
        plans = self.plans()
        if key in ("working", "planned", "today", "late"):
            if not self.can_report:
                raise PermissionDenied("当前岗位无权查看本车间报工。")
            plans = plans.filter(stage="planned" if key == "planned" else "working")
            if key == "late":
                return plans.filter(due_date__lt=self.today)
            if key == "today":
                return plans.filter(due_date=self.today)
            return plans
        plans = plans.filter(stage__in=OPEN_STAGES)
        return plans.filter(due_date=date) if key == "day" else plans.filter(due_date__range=(self.today, self.today + timedelta(days=6)))

    def overview(self):
        plans = self.plans()
        counts = plans.aggregate(working=Count("pk", filter=Q(stage="working")),
                                 late=Count("pk", filter=Q(stage="working", due_date__lt=self.today)),
                                 today=Count("pk", filter=Q(stage="working", due_date=self.today)),
                                 planned=Count("pk", filter=Q(stage="planned")))
        if not self.can_report:
            counts = dict.fromkeys(counts)
        days = [self.today + timedelta(days=i) for i in range(7)]
        daily = dict(plans.filter(stage__in=OPEN_STAGES, due_date__range=(days[0], days[-1])).order_by()
                     .values("due_date").annotate(n=Count("pk")).values_list("due_date", "n"))
        cards = self.jobs(plans.filter(stage="working")[:3])
        return {"as_of": self.today, "workshop": self.workshop, "workshops": self.workshops, "counts": counts,
                "upcoming": [{"date": date, "count": daily.get(date, 0)} for date in days], "jobs": cards}

    def jobs(self, queryset, *, detail=False):
        links = list(queryset.select_related("craft", "schedule_product__product_line__unit", "schedule_product__schedule__production_task"))
        if not links:
            return []
        reports = self.report_lines.filter(report__schedule_product_id__in={link.schedule_product_id for link in links},
                                          report__scheme__scope_craft_id__in={link.craft_id for link in links})
        report_keys = ("report__schedule_product_id", "report__scheme__scope_craft_id", "report__workshop_id")
        latest = {(row.plan_key, row.craft_key, row.shop_key): row for row in
                  reports.annotate(plan_key=F(report_keys[0]), craft_key=F(report_keys[1]), shop_key=F(report_keys[2]))
                  .select_related("report").order_by(*report_keys, *REPORT_ORDER).distinct(*report_keys)}
        totals = {(plan, craft, shop, item, unit): total for plan, craft, shop, item, unit, total in
                  reports.order_by().values(*report_keys, "work_item_id", "unit_name_snapshot").annotate(n=Sum("quantity"))
                  .values_list(*report_keys, "work_item_id", "unit_name_snapshot", "n")}
        operations = defaultdict(list)
        product_ids = {link.schedule_product.product_line_id for link in links}
        if self.workshop != "ASSEMBLY" and has_permission(self.request, SCHEME_PERMISSION):
            schemes = accessible_wage_schemes(self.request, permission=SCHEME_PERMISSION).filter(
                product_line_id__in=product_ids, scope_craft_id__in={link.craft_id for link in links},
                status="APPROVED", effective_from__lte=self.today,
            ).filter(Q(effective_to__gte=self.today) | Q(effective_to__isnull=True))
            for line in WageSchemeLine.objects.filter(scheme__in=schemes, status="ACTIVE").select_related("scheme").order_by("line_number", "id"):
                operations[(line.scheme.product_line_id, line.scheme.scope_craft_id, line.scheme.workshop_id)].append(line)
        receipt_totals = defaultdict(dict)
        if self.can_receipt:
            for prod, unit, total in self.receipts.filter(production_task_product_id__in=product_ids).order_by().values(
                    "production_task_product_id", "unit_id").annotate(n=Sum("received_quantity")).values_list("production_task_product_id", "unit_id", "n"):
                receipt_totals[prod][unit] = total

        result = []
        for link in links:
            plan = link.schedule_product
            product = plan.product_line
            task = plan.schedule.production_task
            key = (plan.pk, link.craft_id, link.craft.workshop_id)
            last = latest.get(key)
            readable = self.can_report and (self.report_shops is None or str(key[2]) in self.report_shops)
            receipt_readable = self.can_receipt and (self.receipt_shops is None or str(key[2]) in self.receipt_shops)
            operation_rows = []
            metric = quantity(reason="暂无可核对的工序数量")
            if self.workshop == "ASSEMBLY":
                received = receipt_totals[product.pk]
                if not receipt_readable:
                    metric = quantity(reason="无成品入库查看权限")
                elif received.keys() - {product.unit_id}:
                    metric = quantity(reason="入库单位与产品单位不一致")
                else:
                    metric = quantity(product.quantity, received.get(product.unit_id, 0), product.unit_name)
            elif readable:
                lines = operations[(product.pk, key[1], key[2])]
                if len({line.scheme_id for line in lines}) == 1:
                    for line in lines:
                        unit = line.unit_name_snapshot
                        count = totals.get((*key, line.work_item_id, unit), 0)
                        item = quantity(line.required_quantity_snapshot, count, unit,
                                        "缺少工序要求数量" if line.required_quantity_snapshot is None else "")
                        operation_rows.append({"name": operation_name(line), **item})
                        if (last and (line.work_item_id, unit) == (last.work_item_id, last.unit_name_snapshot)) or (not last and len(lines) == 1):
                            metric = item
                if last and metric["done"] is None:
                    unit = last.unit_name_snapshot
                    metric = quantity(None, totals[(*key, last.work_item_id, unit)], unit, "缺少当前有效的工序要求数量")
            else:
                metric = quantity(reason="无本车间报工查看权限")
            item = {"id": link.pk, "task_id": task.pk, "task_number": task.task_number,
                    "schedule_number": plan.schedule.schedule_number, "product_name": product.product_name_snapshot,
                    "craft_name": link.craft_name_snapshot, "category": link.plan_category, "stage": link.stage,
                    "due_date": link.due_date, "days_remaining": (link.due_date - self.today).days,
                    "latest_date": last.report.production_date if last else None,
                    "latest_operation": operation_name(last) if last else "", "quantity": metric}
            if detail:
                record_rows = reports.filter(report__schedule_product_id=key[0], report__scheme__scope_craft_id=key[1], report__workshop_id=key[2])
                result.append({"job": item, "operations": operation_rows,
                               "reports": [report_record(row, link.pk) for row in record_rows.select_related(REPORT_CONTEXT).order_by(*REPORT_ORDER)] if readable else None,
                               "receipts": [receipt_record(row, link.pk) for row in self.receipts.filter(production_task_product_id=product.pk)
                                            .select_related("unit", RECEIPT_CONTEXT).order_by("-business_date", "-received_at", "pk")] if receipt_readable else None})
            else:
                result.append(item)
        return result

    def activity(self, params):
        month = {"month": self.today.month, "quarter": (self.today.month - 1) // 3 * 3 + 1, "year": 1}[params["period"]]
        start = self.today.replace(month=month, day=1)
        assembly = self.workshop == "ASSEMBLY"
        available = self.can_receipt if assembly else self.can_report
        data = {"start_date": start, "end_date": self.today, "available": available, "quantities": [], "records": [],
                "task_count": 0, "record_count": 0, "day_count": 0}
        if not available:
            return {"data": data, "meta": {"page": params["page"], "page_size": params["page_size"], "total": 0, "total_pages": 0}}
        if assembly:
            link = self.history_links.filter(schedule_product__product_line_id=OuterRef("production_task_product_id"))
            if self.receipt_shops is not None:
                link = link.filter(craft__workshop_id__in=self.receipt_shops)
            rows = self.receipts.filter(Exists(link), business_date__gte=start).select_related("unit", RECEIPT_CONTEXT).order_by("-business_date", "-received_at", "pk")
            day, task, record, unit, amount = "business_date", "production_task_product__production_task_id", "pk", "unit__unit_name", "received_quantity"
            render = receipt_record
        else:
            link = self.history_links.filter(schedule_product_id=OuterRef("report__schedule_product_id"),
                                     craft_id=OuterRef("report__scheme__scope_craft_id"), craft__workshop_id=OuterRef("report__workshop_id"))
            rows = self.report_lines.filter(Exists(link), report__production_date__gte=start).select_related(REPORT_CONTEXT).order_by(*REPORT_ORDER)
            day, task, record, unit, amount = "report__production_date", "report__product_line__production_task_id", "pk", "unit_name_snapshot", "quantity"
            render = report_record
        data.update(rows.aggregate(task_count=Count(task, distinct=True), day_count=Count(day, distinct=True),
                                   record_count=Count(record, distinct=True)))
        if assembly:
            data["quantities"] = [{"unit": label, "quantity": decimal_string(total)} for label, total in
                                  rows.order_by().values(unit).annotate(n=Sum(amount)).order_by(unit).values_list(unit, "n")]
        # 只有仍可打开的计划才提供当前排产明细入口。
        active_link = link.filter(removed_at__isnull=True, schedule_product__removed_at__isnull=True,
                                  schedule_product__schedule__record_status="ACTIVE",
                                  **{f"{TASK}__status__in": ("READY", "IN_PRODUCTION", "COMPLETED", "PENDING_VALIDATION"),
                                     f"{TASK}__archived_at__isnull": True})
        batch, meta = page_of(rows.annotate(job_id=Subquery(active_link.order_by("pk").values("pk")[:1])), params)
        data["records"] = [render(row, row.job_id) for row in batch]
        return {"data": data, "meta": meta}


def report_record(line, job_id):
    report = line.report
    product = report.product_line
    return {"id": line.pk, "date": report.production_date, "number": report.report_number, "task_number": product.production_task.task_number,
            "product_name": report.product_name_snapshot or product.product_name_snapshot, "name": operation_name(line), "quantity": decimal_string(line.quantity),
            "unit": line.unit_name_snapshot, "job_id": job_id}


def receipt_record(row, job_id):
    product = row.production_task_product
    return {"id": row.pk, "date": row.business_date, "number": row.receipt_number, "task_number": product.production_task.task_number,
            "product_name": row.product_name_snapshot or product.product_name_snapshot, "name": "已确认成品入库", "quantity": str(row.received_quantity),
            "unit": row.unit.unit_name, "job_id": job_id}


def operation_name(line):
    return line.operation_name_snapshot or line.display_name_snapshot
