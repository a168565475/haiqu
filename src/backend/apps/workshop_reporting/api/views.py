from apps.organizations.models import Employee
from ..selectors import reporting_source_products
from apps.access_control.resource_scopes import has_resource_grant
from datetime import date
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from uuid import UUID

from django.conf import settings
from django.db import transaction
from django.db.models import Count, Max, Sum
from django.db.models.functions import Coalesce
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404
from django.utils import timezone
from drf_spectacular.types import OpenApiTypes
from drf_spectacular.utils import extend_schema
from rest_framework import generics, status, viewsets
from rest_framework.decorators import action
from rest_framework.exceptions import PermissionDenied, ValidationError
from rest_framework.response import Response

from apps.core.api.concurrency import etag_for_instance
from apps.core.api.permissions import BusinessActionPermission, HasActiveEmployee
from apps.files.models import USABLE_FILE_SCAN_STATUSES
from apps.production_scheduling.selectors import accessible_production_schedules
from apps.production_scheduling.models import ProductionSchedule, ProductionScheduleProduct, ProductionScheduleProductCraft, ScheduleStatus
from apps.production_tasks.selectors import accessible_production_tasks, production_task_product_image
from apps.workshop_config.models import Craft, Operation, PlanCategory, RecordStatus, Workshop
from apps.workshop_config.selectors import active_employees

from ..models import (
    WageScheme, WageSchemeLineStatus, WageSchemeStatus, WorkReport, WorkReportLine,
    WorkshopPlanExecution, WorkshopPlanStatus,
)
from ..selectors import (
    accessible_wage_schemes, accessible_work_reports, allowed_workshop_ids, search_wage_schemes,
    wage_scheme_line_metrics, wage_schemes_with_context, work_report_cumulative_quantities,
    work_report_selection_sources, work_report_task_cards, work_report_task_products, work_report_tasks,
    work_reports_with_context,
)
from ..schedule_progress import schedule_progress_statuses
from ..schedule_stage_progress import schedule_stage_progress_statuses
from ..services import (
    approve_scheme, create_change_scheme, create_scheme, create_work_report, price_scheme_for, return_scheme, submit_scheme, update_scheme,
    update_work_report, bom_options_for_product_line, wage_scheme_progress,
)
from .serializers import (
    WorkReportDeleteSerializer,
    CommentSerializer, WageSchemeApprovalSerializer, WageSchemeWriteSerializer, WorkReportUpdateSerializer,
    WorkReportWriteSerializer,
    wage_scheme_data, work_report_data,
)


def _uuid(value, field):
    if not value:
        return None
    try:
        return UUID(str(value))
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: "参数不是有效 UUID。"}) from exc


def _date(value, field):
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError) as exc:
        raise ValidationError({field: "日期格式必须为 YYYY-MM-DD。"}) from exc


def _estimated_plan_wage(scheme):
    active_lines = [line for line in scheme.lines.all() if line.status == WageSchemeLineStatus.ACTIVE]
    if not active_lines or any(line.required_quantity_snapshot is None for line in active_lines):
        return None
    total = sum(
        (line.required_quantity_snapshot * line.declared_price for line in active_lines),
        Decimal("0"),
    )
    return str(total.quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP))


def _ensure_workshop_scope(request, workshop_id, *, for_work_reports=False, permission=None):
    allowed = allowed_workshop_ids(request, for_work_reports=for_work_reports, permission=permission)
    if allowed is not None and str(workshop_id) not in {str(pk) for pk in allowed}:
        raise PermissionDenied("当前账号没有该车间的数据权限。")


class ReportingContextView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_reporting_context", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        purpose = request.query_params.get("purpose", "wage_scheme").strip()
        if purpose not in {"wage_scheme", "work_report"}:
            raise ValidationError({"purpose": "上下文用途参数不正确。"})
        required_permission = (
            "workshop_reporting.view_workreport" if purpose == "work_report"
            else "workshop_reporting.view_wagescheme"
        )
        if not (request.user.is_superuser or request.user.has_perm(required_permission)):
            raise PermissionDenied("当前账号没有查看对应业务上下文的权限。")
        schedule_product_id = _uuid(request.query_params.get("schedule_product_id"), "schedule_product_id")
        schedule_product = None
        if schedule_product_id:
            schedule_product = get_object_or_404(
                reporting_source_products(request, required_permission).select_related(
                    "schedule", "schedule__production_task", "product_line", "unit"
                ),
                pk=schedule_product_id, removed_at__isnull=True,
            )
        schedule_products = reporting_source_products(request, required_permission).select_related(
            "schedule", "schedule__production_task", "product_line"
        ).filter(
            removed_at__isnull=True,
        ).order_by("-schedule__created_at", "line_number")[:200]
        workshop_ids = allowed_workshop_ids(request, for_work_reports=purpose == "work_report")
        workshops = Workshop.objects.filter(status=RecordStatus.ACTIVE)
        if workshop_ids is not None:
            workshops = workshops.filter(pk__in=workshop_ids)
        crafts = Craft.objects.filter(status=RecordStatus.ACTIVE, craft_type="INTERNAL", workshop__in=workshops).select_related("workshop")
        if schedule_product:
            craft_ids = schedule_product.crafts.filter(removed_at__isnull=True).values("craft_id")
            crafts = crafts.filter(pk__in=craft_ids)
        operations = Operation.objects.filter(status=RecordStatus.ACTIVE, craft__in=crafts).select_related("craft", "reporting_unit")
        employees = active_employees(Employee.objects.filter(
            workshop__in=workshops
        )).select_related("workshop")
        bom_items = (
            bom_options_for_product_line(schedule_product.product_line_id)
            if schedule_product else []
        )
        return Response({"data": {
            "schedule_product": ({
                "id": str(schedule_product.pk), "product_line_id": str(schedule_product.product_line_id),
                "production_task_id": str(schedule_product.schedule.production_task_id),
                "task_number": schedule_product.schedule.production_task.task_number,
                "order_number": schedule_product.schedule.production_task.order_number,
                "product_name": schedule_product.product_line.product_name_snapshot,
                "product_number": schedule_product.product_line.product_number_snapshot,
                "product_code": schedule_product.product_line.product_code_snapshot,
                "product_specification": schedule_product.product_line.specification_snapshot,
                "product_color": schedule_product.product_line.color_name_snapshot,
                "planned_quantity": str(schedule_product.planned_quantity),
                "order_quantity": str(schedule_product.source_quantity_snapshot),
                "unit_name": schedule_product.unit_name_snapshot,
            } if schedule_product else None),
            "schedule_products": [{
                "id": str(item.pk), "product_line_id": str(item.product_line_id),
                "production_task_id": str(item.schedule.production_task_id),
                "task_number": item.schedule.production_task.task_number,
                "order_number": item.schedule.production_task.order_number,
                "product_name": item.product_line.product_name_snapshot,
                "product_number": item.product_line.product_number_snapshot,
                "product_code": item.product_line.product_code_snapshot,
                "product_specification": item.product_line.specification_snapshot,
                "product_color": item.product_line.color_name_snapshot,
                "planned_quantity": str(item.planned_quantity),
                "order_quantity": str(item.source_quantity_snapshot),
                "unit_name": item.unit_name_snapshot,
            } for item in schedule_products],
            "workshops": [{"id": str(item.pk), "name": item.name} for item in workshops],
            "crafts": [{
                "id": str(item.pk), "name": item.name, "workshop_id": str(item.workshop_id),
                "plan_category": item.plan_category,
            } for item in crafts],
            "operations": [{
                "id": str(item.pk), "operation_number": item.operation_number, "product_name": item.product_name,
                "name": item.name, "craft_id": str(item.craft_id),
                "unit_id": str(item.reporting_unit_id) if item.reporting_unit_id else None,
                "unit_name": item.reporting_unit.unit_name if item.reporting_unit_id else None,
            } for item in operations],
            "bom_items": bom_items,
            "employees": [{"id": str(item.pk), "name": item.display_name, "workshop_id": str(item.workshop_id)} for item in employees],
        }})


class PlanWageStatusView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_reporting_plan_wage_statuses", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        has_reporting_access = (
            request.user.is_superuser
            or request.user.has_perm("workshop_reporting.view_wagescheme")
            or request.user.has_perm("workshop_reporting.view_workreport")
        )
        has_plan_access = (
            request.user.is_superuser
            or request.user.has_perm("production_scheduling.view_productionschedule")
            or request.user.has_perm("production_scheduling.view_all_productionschedule")
        )
        if not has_reporting_access and not has_plan_access:
            raise PermissionDenied("当前账号没有查看内部计划进度的权限。")
        raw_ids = [item.strip() for item in request.query_params.get("schedule_product_ids", "").split(",") if item.strip()]
        if not raw_ids or len(raw_ids) > 100:
            raise ValidationError({"schedule_product_ids": "必须提供 1 至 100 个排产产品 ID。"})
        schedule_product_ids = [_uuid(item, "schedule_product_ids") for item in raw_ids]
        production_date = _date(request.query_params.get("production_date"), "production_date")
        plan_category = request.query_params.get("plan_category", "").strip().upper()
        if not production_date or not plan_category:
            raise ValidationError("production_date、plan_category 均为必填项。")
        if plan_category not in PlanCategory.values:
            raise ValidationError({"plan_category": "计划分类参数不正确。"})
        if has_reporting_access:
            visible_products = (
                reporting_source_products(request, 'workshop_reporting.view_wagescheme')
                | reporting_source_products(request, 'workshop_reporting.view_workreport')
            )
        else:
            visible_products = ProductionScheduleProduct.objects.filter(
                removed_at__isnull=True,
                schedule__record_status=ScheduleStatus.ACTIVE,
                schedule__in=accessible_production_schedules(request),
            )
        products = {
            item.pk: item for item in visible_products.select_related(
                'product_line', 'product_line__production_task'
            ).filter(pk__in=schedule_product_ids)
        }
        links = ProductionScheduleProductCraft.objects.select_related("craft").filter(
            schedule_product_id__in=products, removed_at__isnull=True, plan_category=plan_category
        )
        scopes_by_product = {}
        for link in links:
            scopes_by_product.setdefault(link.schedule_product_id, set()).add(
                (link.craft.workshop_id, link.craft_id)
            )
        if has_reporting_access:
            wage_allowed_ids = allowed_workshop_ids(request)
            report_allowed_ids = allowed_workshop_ids(request, for_work_reports=True)
            report_add_ids = allowed_workshop_ids(
                request, for_work_reports=True, permission="workshop_reporting.add_workreport",
            )
            report_add_set = None if report_add_ids is None else set(report_add_ids)
            wage_allowed_set = None if wage_allowed_ids is None else set(wage_allowed_ids)
            report_allowed_set = None if report_allowed_ids is None else set(report_allowed_ids)
            visible_set = (
                None
                if wage_allowed_set is None or report_allowed_set is None
                else wage_allowed_set | report_allowed_set
            )
        else:
            report_add_set = set()
            report_allowed_set = set()
            visible_set = None
        scope_keys = {
            (products[product_id].product_line_id, next(iter(scopes))[0], next(iter(scopes))[1])
            for product_id, scopes in scopes_by_product.items()
            if len(scopes) == 1 and (visible_set is None or next(iter(scopes))[0] in visible_set)
        }
        schemes = WageScheme.objects.filter(
            product_line_id__in=[key[0] for key in scope_keys],
            workshop_id__in=[key[1] for key in scope_keys],
            scope_craft_id__in=[key[2] for key in scope_keys],
        ).prefetch_related("lines").order_by("-created_at", "-id")
        schemes_by_scope = {}
        for scheme in schemes:
            schemes_by_scope.setdefault(
                (scheme.product_line_id, scheme.workshop_id, scheme.scope_craft_id), []
            ).append(scheme)
        active_schemes = [
            scheme for scheme in schemes
            if scheme.status == WageSchemeStatus.APPROVED
            and scheme.effective_from <= production_date
            and (scheme.effective_to is None or scheme.effective_to >= production_date)
        ]
        work_item_ids = {
            line.work_item_id
            for scheme in active_schemes
            for line in scheme.lines.all()
            if line.status == WageSchemeLineStatus.ACTIVE
        }
        cumulative_by_product = {}
        for row in WorkReportLine.objects.filter(
            report__schedule_product_id__in=products, work_item_id__in=work_item_ids,
        ).values("report__schedule_product_id", "work_item_id").annotate(quantity=Sum("quantity")):
            cumulative_by_product.setdefault(row["report__schedule_product_id"], {})[
                row["work_item_id"]
            ] = row["quantity"]
        executions = {
            (item.schedule_product_id, item.craft_id): item
            for item in WorkshopPlanExecution.objects.filter(
                schedule_product_id__in=products,
                craft_id__in=[key[2] for key in scope_keys],
            )
        }
        rows = []
        for product_id in schedule_product_ids:
            product = products.get(product_id)
            scopes = scopes_by_product.get(product_id, set())
            if not product or len(scopes) != 1:
                rows.append({
                    "schedule_product_id": str(product_id), "workshop_id": None,
                    "craft_id": None, "status": "UNAVAILABLE", "scheme_id": None,
                    "can_report": False, "reason": "未找到唯一的厂内工艺范围。",
                    "estimated_wage": None,
                    "progress_percent": None, "plan_status": WorkshopPlanStatus.IN_PROGRESS,
                    "plan_status_display": "进行中",
                })
                continue
            workshop_id, craft_id = next(iter(scopes))
            if visible_set is not None and workshop_id not in visible_set:
                rows.append({
                    "schedule_product_id": str(product_id), "workshop_id": str(workshop_id),
                    "craft_id": str(craft_id), "status": "FORBIDDEN", "scheme_id": None,
                    "can_report": False, "reason": "当前账号没有该车间权限。",
                    "estimated_wage": None,
                    "progress_percent": None, "plan_status": WorkshopPlanStatus.IN_PROGRESS,
                    "plan_status_display": "进行中",
                })
                continue
            report_allowed = report_allowed_set is None or workshop_id in report_allowed_set
            can_create_report = request.user.is_superuser or (
                request.user.has_perm("workshop_reporting.add_workreport")
                and request.user.has_perm("workshop_reporting.view_workreport")
            )
            candidates = schemes_by_scope.get((product.product_line_id, workshop_id, craft_id), [])
            active = [item for item in candidates if item.status == WageSchemeStatus.APPROVED and item.effective_from <= production_date and (item.effective_to is None or item.effective_to >= production_date)]
            execution = executions.get((product_id, craft_id))
            plan_status = execution.status if execution else WorkshopPlanStatus.IN_PROGRESS
            plan_status_display = execution.get_status_display() if execution else "进行中"
            if len(active) == 1:
                progress = wage_scheme_progress(active[0], cumulative_by_product.get(product_id, {}))
                if plan_status == WorkshopPlanStatus.COMPLETED:
                    from apps.workshop_reporting.tube_plan_services import is_current_tube_scheme, tube_plan_is_complete
                    if is_current_tube_scheme(active[0]) and not tube_plan_is_complete(
                        product_id, active[0], cumulative_by_work_item=cumulative_by_product.get(product_id, {}),
                    ):
                        # 管材工序规则变化后，允许只读提示继续报工；实际状态在报工事务中重开。
                        plan_status = WorkshopPlanStatus.IN_PROGRESS
                        plan_status_display = '进行中'
                can_report = (
                    plan_status != WorkshopPlanStatus.COMPLETED
                    and progress is not None
                    and report_allowed and can_create_report
                    and (report_add_set is None or workshop_id in report_add_set)
                )
                reason = "" if can_report else "当前账号没有该车间的报工权限。"
                if progress is None:
                    reason = "工价方案缺少需完成次数，请变更并重新批准。"
                if plan_status == WorkshopPlanStatus.COMPLETED:
                    reason = "当前生产计划已完成。"
                rows.append({
                    "schedule_product_id": str(product_id), "workshop_id": str(workshop_id),
                    "craft_id": str(craft_id), "status": WageSchemeStatus.APPROVED,
                    "scheme_id": str(active[0].pk), "can_report": can_report, "reason": reason,
                    "estimated_wage": _estimated_plan_wage(active[0]),
                    "progress_percent": progress["percentage"] if progress else None,
                    "plan_status": plan_status, "plan_status_display": plan_status_display,
                })
            elif len(active) > 1:
                rows.append({
                    "schedule_product_id": str(product_id), "workshop_id": str(workshop_id),
                    "craft_id": str(craft_id), "status": "CONFLICT", "scheme_id": None,
                    "can_report": False, "reason": "当前日期存在多个适用工价版本。",
                    "estimated_wage": None,
                    "progress_percent": None, "plan_status": plan_status,
                    "plan_status_display": plan_status_display,
                })
            else:
                latest = candidates[0] if candidates else None
                latest_status = latest.status if latest and latest.status != WageSchemeStatus.APPROVED else "NO_EFFECTIVE_VERSION"
                rows.append({
                    "schedule_product_id": str(product_id), "workshop_id": str(workshop_id),
                    "craft_id": str(craft_id), "status": latest_status if latest else "NOT_CREATED",
                    "scheme_id": str(latest.pk) if latest else None, "can_report": False,
                    "reason": "当前日期没有适用的已批准工价方案。",
                    "estimated_wage": _estimated_plan_wage(latest) if latest else None,
                    "progress_percent": None, "plan_status": plan_status,
                    "plan_status_display": plan_status_display,
                })
        return Response({"data": rows})


class ScheduleProgressStatusView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_reporting_schedule_progress_statuses", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        if not (
            request.user.is_superuser
            or request.user.has_perm("production_scheduling.view_productionschedule")
            or request.user.has_perm("production_scheduling.view_all_productionschedule")
        ):
            raise PermissionDenied("当前账号没有查看排产计划的权限。")
        raw_ids = [item.strip() for item in request.query_params.get("schedule_ids", "").split(",") if item.strip()]
        if not raw_ids or len(raw_ids) > 100:
            raise ValidationError({"schedule_ids": "必须提供 1 至 100 个排产计划 ID。"})
        schedule_ids = [_uuid(item, "schedule_ids") for item in raw_ids]
        production_date = _date(request.query_params.get("production_date"), "production_date") or timezone.localdate()
        visible_schedule_ids = set(
            accessible_production_schedules(request).filter(
                pk__in=schedule_ids, record_status=ScheduleStatus.ACTIVE,
            ).values_list("pk", flat=True)
        )
        ordered_ids = [schedule_id for schedule_id in schedule_ids if schedule_id in visible_schedule_ids]
        rows = schedule_progress_statuses(ordered_ids, production_date=production_date)
        stage_rows = schedule_stage_progress_statuses(
            ordered_ids, request=request, as_of_date=production_date,
        )
        for row in rows:
            row.update(stage_rows[row["schedule_id"]])
        return Response({"data": rows})


class WageSchemeViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    serializer_class = WageSchemeWriteSerializer
    action_permission_map = {
        "list": "workshop_reporting.view_wagescheme", "retrieve": "workshop_reporting.view_wagescheme",
        "history": "workshop_reporting.view_wagescheme", "create": "workshop_reporting.add_wagescheme",
        "partial_update": "workshop_reporting.change_wagescheme", "submit": "workshop_reporting.submit_wagescheme",
        "change": "workshop_reporting.change_wagescheme",
        "approve": "workshop_reporting.approve_wagescheme", "return_scheme": "workshop_reporting.approve_wagescheme",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WageScheme.objects.none()
        return wage_schemes_with_context(accessible_wage_schemes(self.request))

    def list(self, request):
        queryset = search_wage_schemes(self.get_queryset(), request.query_params.get("search", "").strip())
        status_value = request.query_params.get("status", "").strip().upper()
        if status_value:
            if status_value not in WageSchemeStatus.values:
                raise ValidationError({"status": "工价方案状态参数不正确。"})
            queryset = queryset.filter(status=status_value)
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        craft_id = _uuid(request.query_params.get("craft_id"), "craft_id")
        if workshop_id:
            queryset = queryset.filter(workshop_id=workshop_id)
        if craft_id:
            queryset = queryset.filter(scope_craft_id=craft_id)
        scheme_type = request.query_params.get("scheme_type", "").strip().upper()
        if scheme_type:
            if scheme_type not in {"NEW", "CHANGE"}:
                raise ValidationError({"scheme_type": "工价方案类型参数不正确。"})
            queryset = queryset.filter(parent_scheme__isnull=scheme_type == "NEW")
        updated_from = _date(request.query_params.get("updated_from"), "updated_from")
        updated_to = _date(request.query_params.get("updated_to"), "updated_to")
        if updated_from and updated_to and updated_from > updated_to:
            raise ValidationError({"updated_to": "更新日期结束时间不能早于开始时间。"})
        if updated_from:
            queryset = queryset.filter(updated_at__date__gte=updated_from)
        if updated_to:
            queryset = queryset.filter(updated_at__date__lte=updated_to)
        ordering = request.query_params.get("ordering", "-updated_at")
        if ordering not in {"updated_at", "-updated_at", "created_at", "-created_at", "scheme_number", "-scheme_number", "effective_from", "-effective_from"}:
            raise ValidationError({"ordering": "排序参数不正确。"})
        page = self.paginate_queryset(queryset.order_by(ordering, "-id"))
        return self.get_paginated_response([wage_scheme_data(item, detail=False) for item in page])

    def retrieve(self, request, pk=None):
        scheme = get_object_or_404(self.get_queryset(), pk=pk)
        response = Response({"data": wage_scheme_data(
            scheme, line_metrics=wage_scheme_line_metrics(request, scheme),
        )})
        response["ETag"] = etag_for_instance(scheme)
        return response

    def create(self, request):
        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        workshop_id = serializer.validated_data["workshop_id"]
        _ensure_workshop_scope(request, workshop_id)
        product_line_id = serializer.validated_data["product_line_id"]
        if not has_resource_grant(request, "workshop_reporting.add_wagescheme", "WORKSHOP") and not accessible_production_tasks(request).filter(products__id=product_line_id).exists():
            raise PermissionDenied("生产任务产品不存在或不可访问。")
        history_source_id = serializer.validated_data.get("history_source_scheme_id")
        if history_source_id and not accessible_wage_schemes(request, permission="workshop_reporting.view_wagescheme").filter(pk=history_source_id, status=WageSchemeStatus.APPROVED).exists():
            raise ValidationError({"history_source_scheme_id": "历史方案不存在、未批准或不可访问。"})
        scheme = create_scheme(data=dict(serializer.validated_data), actor=request.employee, request=request)
        scheme = self.get_queryset().get(pk=scheme.pk)
        response = Response({"data": wage_scheme_data(scheme)}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(scheme)
        return response

    @action(detail=True, methods=["post"])
    def change(self, request, pk=None):
        source = get_object_or_404(accessible_wage_schemes(request), pk=pk)
        from apps.access_control.resource_scopes import enabled
        if enabled():
            _ensure_workshop_scope(request, source.workshop_id, permission='workshop_reporting.submit_wagescheme')
        serializer = self.get_serializer(data=request.data); serializer.is_valid(raise_exception=True)
        if serializer.validated_data["product_line_id"] != source.product_line_id or serializer.validated_data["workshop_id"] != source.workshop_id:
            raise ValidationError("变更版本必须保持原生产任务产品和车间。")
        scheme = create_change_scheme(
            source_scheme_id=source.pk, data=dict(serializer.validated_data), actor=request.employee, request=request
        )
        scheme = self.get_queryset().get(pk=scheme.pk)
        response = Response({"data": wage_scheme_data(scheme)}, status=status.HTTP_201_CREATED)
        response["ETag"] = etag_for_instance(scheme)
        return response

    def partial_update(self, request, pk=None):
        current = get_object_or_404(accessible_wage_schemes(request), pk=pk)
        serializer = self.get_serializer(instance=current, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        _ensure_workshop_scope(request, serializer.validated_data.get('workshop_id', current.workshop_id))
        scheme = update_scheme(
            scheme_id=current.pk, data=dict(serializer.validated_data), actor=request.employee, request=request
        )
        scheme = self.get_queryset().get(pk=scheme.pk)
        response = Response({"data": wage_scheme_data(scheme)})
        response["ETag"] = etag_for_instance(scheme)
        return response

    @action(detail=True, methods=["post"])
    def submit(self, request, pk=None):
        current = get_object_or_404(accessible_wage_schemes(request), pk=pk)
        serializer = CommentSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        scheme = submit_scheme(
            scheme_id=current.pk, actor=request.employee, request=request,
            comment=serializer.validated_data.get("comment", ""),
        )
        scheme = self.get_queryset().get(pk=scheme.pk)
        response = Response({"data": wage_scheme_data(scheme)}); response["ETag"] = etag_for_instance(scheme)
        return response

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        current = get_object_or_404(accessible_wage_schemes(request), pk=pk)
        serializer = WageSchemeApprovalSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        scheme = approve_scheme(
            scheme_id=current.pk, actor=request.employee, request=request, **serializer.validated_data
        )
        scheme = self.get_queryset().get(pk=scheme.pk)
        response = Response({"data": wage_scheme_data(scheme)}); response["ETag"] = etag_for_instance(scheme)
        return response

    @action(detail=True, methods=["post"], url_path="return")
    def return_scheme(self, request, pk=None):
        current = get_object_or_404(accessible_wage_schemes(request), pk=pk)
        serializer = CommentSerializer(data=request.data); serializer.is_valid(raise_exception=True)
        scheme = return_scheme(
            scheme_id=current.pk, actor=request.employee, request=request,
            comment=serializer.validated_data.get("comment", ""),
        )
        scheme = self.get_queryset().get(pk=scheme.pk)
        response = Response({"data": wage_scheme_data(scheme)}); response["ETag"] = etag_for_instance(scheme)
        return response

    @action(detail=False, methods=["get"], url_path="history-schemes")
    def history(self, request):
        queryset = self.get_queryset().filter(status=WageSchemeStatus.APPROVED)
        product_line_id = _uuid(request.query_params.get("product_line_id"), "product_line_id")
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        craft_id = _uuid(request.query_params.get("craft_id"), "craft_id")
        if product_line_id: queryset = queryset.filter(product_line_id=product_line_id)
        if workshop_id: queryset = queryset.filter(workshop_id=workshop_id)
        if craft_id: queryset = queryset.filter(scope_craft_id=craft_id)
        page = self.paginate_queryset(queryset.order_by("-effective_from", "-approved_at", "-id"))
        return self.get_paginated_response([wage_scheme_data(item) for item in page])


class WorkReportViewSet(viewsets.GenericViewSet):
    permission_classes = [HasActiveEmployee, BusinessActionPermission]
    serializer_class = WorkReportWriteSerializer
    action_permission_map = {
        "list": "workshop_reporting.view_workreport",
        "create": "workshop_reporting.add_workreport", "retrieve": "workshop_reporting.view_workreport",
        "partial_update": "workshop_reporting.change_workreport",
        "destroy": "workshop_reporting.delete_workreport",
        "price_context": "workshop_reporting.view_workreport",
    }

    def get_queryset(self):
        if getattr(self, "swagger_fake_view", False):
            return WorkReport.objects.none()
        return work_reports_with_context(accessible_work_reports(self.request))

    @extend_schema(operation_id="workshop_reporting_work_report_list", responses=OpenApiTypes.OBJECT)
    def list(self, request):
        queryset = self.get_queryset()
        production_task_id = _uuid(request.query_params.get("production_task_id"), "production_task_id")
        schedule_product_id = _uuid(request.query_params.get("schedule_product_id"), "schedule_product_id")
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        craft_id = _uuid(request.query_params.get("craft_id"), "craft_id")
        if production_task_id: queryset = queryset.filter(product_line__production_task_id=production_task_id)
        if schedule_product_id: queryset = queryset.filter(schedule_product_id=schedule_product_id)
        if workshop_id: queryset = queryset.filter(workshop_id=workshop_id)
        if craft_id: queryset = queryset.filter(scheme__scope_craft_id=craft_id)
        page = list(self.paginate_queryset(queryset.order_by("-production_date", "-created_at", "-id")))
        cumulative = work_report_cumulative_quantities(queryset)
        payload = []
        for report in page:
            line_metrics = {
                line.pk: {"cumulative_quantity": str(cumulative.get(
                    (report.schedule_product_id, report.workshop_id, line.work_item_id), 0,
                ))}
                for line in report.lines.all()
            }
            payload.append(work_report_data(report, line_metrics=line_metrics, request=request))
        return self.get_paginated_response(payload)

    @transaction.atomic
    def create(self, request):
        serializer = self.get_serializer(data=request.data); serializer.is_valid(raise_exception=True)
        scheme = get_object_or_404(WageScheme.objects.all(), pk=serializer.validated_data["scheme_id"])
        _ensure_workshop_scope(request, scheme.workshop_id, for_work_reports=True)
        report = create_work_report(data=dict(serializer.validated_data), actor=request.employee, request=request)
        report = self.get_queryset().get(pk=report.pk)
        return Response({"data": work_report_data(report, request=request)}, status=status.HTTP_201_CREATED)

    def retrieve(self, request, pk=None):
        report = get_object_or_404(self.get_queryset(), pk=pk)
        response = Response({"data": work_report_data(report, request=request)})
        response["ETag"] = etag_for_instance(report)
        return response

    @transaction.atomic
    def partial_update(self, request, pk=None):
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = WorkReportUpdateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        _ensure_workshop_scope(request, current.workshop_id, for_work_reports=True)
        report = update_work_report(
            report_id=current.pk, data=dict(serializer.validated_data), actor=request.employee, request=request
        )
        report = self.get_queryset().get(pk=report.pk)
        response = Response({"data": work_report_data(report, request=request)})
        response["ETag"] = etag_for_instance(report)
        return response

    @extend_schema(request=WorkReportDeleteSerializer, responses={204: None})
    def destroy(self, request, pk=None):
        from ..deletion_services import delete_work_report
        current = get_object_or_404(self.get_queryset(), pk=pk)
        serializer = WorkReportDeleteSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        delete_work_report(report_id=current.pk, reason=serializer.validated_data['reason'],
                           actor=request.employee, request=request)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=["get"], url_path="price-context")
    def price_context(self, request):
        product_line_id = _uuid(request.query_params.get("product_line_id"), "product_line_id")
        schedule_product_id = _uuid(request.query_params.get("schedule_product_id"), "schedule_product_id")
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        craft_id = _uuid(request.query_params.get("craft_id"), "craft_id")
        production_date = _date(request.query_params.get("production_date"), "production_date")
        if not all((product_line_id, workshop_id, craft_id, production_date)):
            raise ValidationError("product_line_id、workshop_id、craft_id、production_date 均为必填项。")
        _ensure_workshop_scope(request, workshop_id, for_work_reports=True)
        scheme = price_scheme_for(
            product_line_id=product_line_id, workshop_id=workshop_id,
            craft_id=craft_id, production_date=production_date,
        )
        scheme = wage_schemes_with_context(WageScheme.objects.filter(pk=scheme.pk)).get()
        visible_reports = accessible_work_reports(request).filter(
            product_line_id=product_line_id, workshop_id=workshop_id
        )
        line_queryset = WorkReportLine.objects.filter(report__in=visible_reports)
        cumulative = {
            row["work_item_id"]: row["quantity"]
            for row in line_queryset.values("work_item_id").annotate(quantity=Sum("quantity"))
        }
        day_quantities = {
            row["work_item_id"]: row["quantity"]
            for row in line_queryset.filter(report__production_date=production_date)
            .values("work_item_id").annotate(quantity=Sum("quantity"))
        }
        latest_employee_by_work_item = {}
        if schedule_product_id:
            latest_lines = WorkReportLine.objects.filter(
                report__in=visible_reports,
                report__schedule_product_id=schedule_product_id,
                report__scheme__scope_craft_id=craft_id,
                workshop_employee__in=active_employees(Employee.objects.all()),
            ).order_by("-report__updated_at", "-line_number", "-id").values(
                "work_item_id", "workshop_employee_id"
            )
            for row in latest_lines:
                latest_employee_by_work_item.setdefault(
                    row["work_item_id"], str(row["workshop_employee_id"])
                )
        data = wage_scheme_data(scheme)
        for line in data["lines"]:
            work_item_id = UUID(line["work_item_id"])
            line["cumulative_quantity"] = str(cumulative.get(work_item_id, 0))
            line["production_date_quantity"] = str(day_quantities.get(work_item_id, 0))
            line["last_workshop_employee_id"] = latest_employee_by_work_item.get(work_item_id)
        return Response({"data": data})


class WorkReportTaskListView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_reporting_work_report_task_list", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        from apps.access_control.module_policy import has_permission

        if not has_permission(request, "workshop_reporting.view_workreport"):
            raise PermissionDenied("当前账号没有查看报工记录的权限。")
        reports, crafts = work_report_selection_sources(request)
        tasks = work_report_tasks(reports, crafts, request.query_params.get("q", "").strip())
        production_task_id = _uuid(request.query_params.get("production_task_id"), "production_task_id")
        if production_task_id:
            tasks = tasks.filter(pk=production_task_id)
        page = list(self.paginate_queryset(tasks))
        return self.get_paginated_response(work_report_task_cards(page, reports, crafts))


class WorkReportTaskProductImageView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(
        operation_id="workshop_reporting_work_report_task_product_image",
        responses={(200, "application/octet-stream"): OpenApiTypes.BINARY},
    )
    def get(self, request, task_id, product_line_id):
        from apps.access_control.module_policy import has_permission

        if not has_permission(request, "workshop_reporting.view_workreport"):
            raise PermissionDenied("当前账号没有查看报工记录的权限。")
        reports, crafts = work_report_selection_sources(request)
        product = get_object_or_404(
            work_report_task_products(reports, crafts),
            pk=_uuid(product_line_id, "product_line_id"),
            production_task_id=_uuid(task_id, "production_task_id"),
        )
        image = production_task_product_image(product)
        if image is None or image.scan_status not in USABLE_FILE_SCAN_STATUSES or not image.content_type.startswith("image/"):
            raise Http404("产品图片不可用。")
        media_root = Path(settings.MEDIA_ROOT).resolve()
        storage_path = (media_root / image.storage_key).resolve()
        try:
            storage_path.relative_to(media_root)
        except ValueError as exc:
            raise Http404("文件路径无效。") from exc
        if not storage_path.is_file():
            raise Http404("文件不存在。")
        return FileResponse(storage_path.open("rb"), content_type=image.content_type, filename=image.original_name)


class WorkReportDayListView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_reporting_work_report_day_list", responses=OpenApiTypes.OBJECT)
    def get(self, request):
        from apps.access_control.module_policy import has_permission

        if not has_permission(request, "workshop_reporting.view_workreport"):
            raise PermissionDenied("当前账号没有查看报工记录的权限。")
        queryset = accessible_work_reports(request, permission="workshop_reporting.view_workreport")
        production_task_id = _uuid(request.query_params.get("production_task_id"), "production_task_id")
        schedule_product_id = _uuid(request.query_params.get("schedule_product_id"), "schedule_product_id")
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        craft_id = _uuid(request.query_params.get("craft_id"), "craft_id")
        date_from = _date(request.query_params.get("date_from"), "date_from")
        date_to = _date(request.query_params.get("date_to"), "date_to")
        if production_task_id: queryset = queryset.filter(product_line__production_task_id=production_task_id)
        if schedule_product_id: queryset = queryset.filter(schedule_product_id=schedule_product_id)
        if workshop_id: queryset = queryset.filter(workshop_id=workshop_id)
        if craft_id: queryset = queryset.filter(scheme__scope_craft_id=craft_id)
        if date_from: queryset = queryset.filter(production_date__gte=date_from)
        if date_to: queryset = queryset.filter(production_date__lte=date_to)
        rows = queryset.values("production_date").annotate(
            report_count=Count("id", distinct=True), order_count=Count("product_line__production_task_id", distinct=True),
            product_count=Count("product_line_id", distinct=True), employee_count=Count(Coalesce("lines__workshop_employee_id", "lines__legacy_employee_id"), distinct=True),
            line_count=Count("lines__id", distinct=True), total_amount=Sum("lines__amount"), last_saved_at=Max("updated_at"),
        ).order_by("-production_date")
        page = self.paginate_queryset(rows)
        return self.get_paginated_response([{**row, "total_amount": str(row["total_amount"] or 0)} for row in page])


class WorkReportDayDetailView(generics.GenericAPIView):
    permission_classes = [HasActiveEmployee]

    @extend_schema(operation_id="workshop_reporting_work_report_day_detail", responses=OpenApiTypes.OBJECT)
    def get(self, request, production_date):
        from apps.access_control.module_policy import has_permission

        if not has_permission(request, "workshop_reporting.view_workreport"):
            raise PermissionDenied("当前账号没有查看报工记录的权限。")
        day = _date(production_date, "production_date")
        visible_reports = accessible_work_reports(request, permission="workshop_reporting.view_workreport")
        queryset = self.filter_queryset(work_reports_with_context(visible_reports.filter(production_date=day)))
        production_task_id = _uuid(request.query_params.get("production_task_id"), "production_task_id")
        schedule_product_id = _uuid(request.query_params.get("schedule_product_id"), "schedule_product_id")
        workshop_id = _uuid(request.query_params.get("workshop_id"), "workshop_id")
        craft_id = _uuid(request.query_params.get("craft_id"), "craft_id")
        if production_task_id: queryset = queryset.filter(product_line__production_task_id=production_task_id)
        if schedule_product_id: queryset = queryset.filter(schedule_product_id=schedule_product_id)
        if workshop_id: queryset = queryset.filter(workshop_id=workshop_id)
        if craft_id: queryset = queryset.filter(scheme__scope_craft_id=craft_id)
        page = list(self.paginate_queryset(queryset.order_by("created_at", "id")))

        cumulative_reports = visible_reports
        if production_task_id:
            cumulative_reports = cumulative_reports.filter(product_line__production_task_id=production_task_id)
        if schedule_product_id:
            cumulative_reports = cumulative_reports.filter(schedule_product_id=schedule_product_id)
        if workshop_id:
            cumulative_reports = cumulative_reports.filter(workshop_id=workshop_id)
        if craft_id:
            cumulative_reports = cumulative_reports.filter(scheme__scope_craft_id=craft_id)
        cumulative_by_scope = work_report_cumulative_quantities(cumulative_reports)

        payload = []
        for report in page:
            line_metrics = {}
            for line in report.lines.all():
                line_metrics[line.pk] = {
                    "cumulative_quantity": str(cumulative_by_scope.get(
                        (report.schedule_product_id, report.workshop_id, line.work_item_id), 0
                    )),
                    "required_quantity": (
                        str(line.required_quantity_snapshot)
                        if line.required_quantity_snapshot is not None else None
                    ),
                }
            payload.append(work_report_data(report, line_metrics=line_metrics, request=request))
        return self.get_paginated_response(payload)
